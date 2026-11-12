"""Sign-in sessions stay signed in only while they carry the account's generation."""

import os
import tempfile
import unittest

from werkzeug.security import generate_password_hash

import app as sotto


class SessionGenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self._old = {}
        for name, value in {
            "USERS_PATH": os.path.join(root, "users.json"),
            "TOKENS_PATH": os.path.join(root, "tokens.json"),
            "API_TOKENS_PATH": os.path.join(root, "api_tokens.json"),
            "LOG_PATH": os.path.join(root, "lector.log"),
            "LIBRARY_DIR": os.path.join(root, "library"),
            "SHARES_PATH": os.path.join(root, "shares.json"),
        }.items():
            self._old[name] = getattr(sotto, name)
            setattr(sotto, name, value)
        os.makedirs(sotto.LIBRARY_DIR, exist_ok=True)
        sotto._api_rate.clear()
        self.addCleanup(self._restore)
        self.addCleanup(self.tmp.cleanup)

    def _restore(self):
        for name, value in self._old.items():
            setattr(sotto, name, value)

    def write_user(self, email, password, **extra):
        users = sotto.load_users()
        record = {"pw": generate_password_hash(password)}
        record.update(extra)
        users[email] = record
        sotto.save_users(users)

    def client(self):
        return sotto.app.test_client()

    def csrf_of(self, client):
        with client.session_transaction() as sess:
            token = sess.get("csrf")
        if token:
            return token
        client.get("/login")
        with client.session_transaction() as sess:
            return sess["csrf"]

    def sign_in(self, client, email, password):
        token = self.csrf_of(client)
        return client.post(
            "/login",
            data={"username": email, "password": password, "_csrf": token},
            follow_redirects=False,
        )

    def log_out(self, client):
        return client.post(
            "/logout",
            data={"_csrf": self.csrf_of(client)},
            follow_redirects=False,
        )

    def account(self, client):
        return client.get("/account", follow_redirects=False)

    def test_sign_in_is_accepted_only_while_the_session_carries_the_account_generation(self):
        self.write_user("ada@example.com", "correct-horse", session_generation=2)
        client = self.client()
        self.sign_in(client, "ada@example.com", "correct-horse")
        with client.session_transaction() as sess:
            self.assertEqual(sess.get("session_generation"), 2)
        self.assertEqual(self.account(client).status_code, 200)
        with client.session_transaction() as sess:
            sess["session_generation"] = 1
        rejected = self.account(client)
        self.assertEqual(rejected.status_code, 302)
        self.assertTrue(rejected.headers["Location"].startswith("/login"))

    def test_an_account_with_no_generation_yet_is_at_the_starting_generation(self):
        self.write_user("ada@example.com", "correct-horse")
        client = self.client()
        self.sign_in(client, "ada@example.com", "correct-horse")
        with client.session_transaction() as sess:
            self.assertEqual(sess.get("session_generation"), 0)
        carried = self.client()
        with carried.session_transaction() as sess:
            sess["user"] = "ada@example.com"
            sess["session_generation"] = 0
        self.assertEqual(self.account(carried).status_code, 200)
        bare = self.client()
        with bare.session_transaction() as sess:
            sess["user"] = "ada@example.com"
        rejected = self.account(bare)
        self.assertEqual(rejected.status_code, 302)
        self.assertTrue(rejected.headers["Location"].startswith("/login"))

    def test_a_cross_site_get_logout_does_not_sign_out_other_sessions(self):
        # SameSite=Lax still attaches the session cookie to a top-level
        # cross-site GET. That request must not advance the account generation.
        self.write_user("ada@example.com", "correct-horse")
        ada = self.client()
        other = self.client()
        self.sign_in(ada, "ada@example.com", "correct-horse")
        self.sign_in(other, "ada@example.com", "correct-horse")
        crossed = ada.get(
            "/logout",
            headers={
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "document",
            },
            follow_redirects=False,
        )
        self.assertEqual(crossed.status_code, 302)
        self.assertEqual(self.account(other).status_code, 200)
        self.assertEqual(
            sotto.load_users()["ada@example.com"].get("session_generation", 0), 0
        )

    def test_log_out_signs_out_every_session_for_that_account(self):
        self.write_user("ada@example.com", "correct-horse")
        self.write_user("bea@example.com", "correct-horse")
        ada = self.client()
        other = self.client()
        bea = self.client()
        self.sign_in(ada, "ada@example.com", "correct-horse")
        self.sign_in(other, "ada@example.com", "correct-horse")
        self.sign_in(bea, "bea@example.com", "correct-horse")
        home = ada.get("/", follow_redirects=False)
        self.assertEqual(home.status_code, 200)
        self.assertIn(b'method=post action="/logout"', home.data)
        self.assertIn(self.csrf_of(ada).encode(), home.data)
        self.assertNotIn(b'href="/logout"', home.data)
        self.assertEqual(self.log_out(ada).status_code, 302)
        self.assertEqual(self.account(ada).status_code, 302)
        self.assertEqual(self.account(other).status_code, 302)
        self.assertEqual(self.account(bea).status_code, 200)
        self.sign_in(ada, "ada@example.com", "correct-horse")
        self.assertEqual(self.account(ada).status_code, 200)
        self.assertEqual(self.account(other).status_code, 302)

    def change_password(self, client, current, new):
        return client.post(
            "/account",
            data={"current": current, "new": new, "_csrf": self.csrf_of(client)},
            follow_redirects=False,
        )

    def test_password_change_keeps_this_browser_and_signs_out_the_others(self):
        self.write_user("ada@example.com", "correct-horse")
        self.write_user("bea@example.com", "correct-horse")
        here = self.client()
        there = self.client()
        bea = self.client()
        self.sign_in(here, "ada@example.com", "correct-horse")
        self.sign_in(there, "ada@example.com", "correct-horse")
        self.sign_in(bea, "bea@example.com", "correct-horse")
        changed = self.change_password(here, "correct-horse", "new-password-1")
        self.assertEqual(changed.status_code, 200)
        self.assertIn(b"Password changed.", changed.data)
        self.assertIn(b"log out", changed.data)
        self.assertEqual(self.account(here).status_code, 200)
        self.assertEqual(self.account(there).status_code, 302)
        self.assertEqual(self.account(bea).status_code, 200)
        again = self.client()
        self.sign_in(again, "ada@example.com", "new-password-1")
        self.assertEqual(self.account(again).status_code, 200)
        stale = self.client()
        self.sign_in(stale, "ada@example.com", "correct-horse")
        self.assertEqual(self.account(stale).status_code, 302)

    def test_rejected_password_change_does_not_sign_anyone_out(self):
        self.write_user("ada@example.com", "correct-horse")
        here = self.client()
        there = self.client()
        self.sign_in(here, "ada@example.com", "correct-horse")
        self.sign_in(there, "ada@example.com", "correct-horse")
        wrong = self.change_password(here, "wrong-password", "new-password-1")
        self.assertEqual(wrong.status_code, 200)
        self.assertIn(b"Current password is incorrect.", wrong.data)
        short = self.change_password(here, "correct-horse", "short")
        self.assertEqual(short.status_code, 200)
        self.assertIn(b"New password must be at least 8 characters.", short.data)
        self.assertEqual(self.account(here).status_code, 200)
        self.assertEqual(self.account(there).status_code, 200)

    def save_password_from_link(self, kind, email, new):
        token = sotto.new_token(email, kind, 3600)
        client = self.client()
        saved = client.post(
            "/reset/" + token,
            data={"new": new, "_csrf": self.csrf_of(client)},
            follow_redirects=False,
        )
        return saved

    def test_saving_a_password_from_a_reset_link_signs_out_existing_sessions(self):
        self.write_user("ada@example.com", "correct-horse")
        self.write_user("bea@example.com", "correct-horse")
        ada = self.client()
        bea = self.client()
        self.sign_in(ada, "ada@example.com", "correct-horse")
        self.sign_in(bea, "bea@example.com", "correct-horse")
        saved = self.save_password_from_link("reset", "ada@example.com", "new-password-1")
        self.assertEqual(saved.status_code, 200)
        self.assertIn(b"Your password is set.", saved.data)
        self.assertNotIn(b"log out", saved.data)
        self.assertEqual(self.account(ada).status_code, 302)
        self.assertEqual(self.account(bea).status_code, 200)
        again = self.client()
        self.sign_in(again, "ada@example.com", "new-password-1")
        self.assertEqual(self.account(again).status_code, 200)
        stale = self.client()
        self.sign_in(stale, "ada@example.com", "correct-horse")
        self.assertEqual(self.account(stale).status_code, 302)

    def test_a_rejected_reset_does_not_sign_out_existing_sessions(self):
        self.write_user("ada@example.com", "correct-horse")
        ada = self.client()
        self.sign_in(ada, "ada@example.com", "correct-horse")
        saved = self.save_password_from_link("reset", "ada@example.com", "short")
        self.assertEqual(saved.status_code, 200)
        self.assertIn(b"Password must be at least 8 characters.", saved.data)
        self.assertEqual(self.account(ada).status_code, 200)

    def test_saving_a_password_from_an_invite_link_signs_out_existing_sessions(self):
        self.write_user("ada@example.com", "correct-horse")
        ada = self.client()
        self.sign_in(ada, "ada@example.com", "correct-horse")
        saved = self.save_password_from_link("invite", "ada@example.com", "new-password-1")
        self.assertEqual(saved.status_code, 200)
        self.assertIn(b"Your password is set.", saved.data)
        self.assertEqual(self.account(ada).status_code, 302)
        again = self.client()
        self.sign_in(again, "ada@example.com", "new-password-1")
        self.assertEqual(self.account(again).status_code, 200)

    def test_requesting_a_reset_does_not_sign_out(self):
        self.write_user("ada@example.com", "correct-horse")
        ada = self.client()
        self.sign_in(ada, "ada@example.com", "correct-horse")
        sent = ada.post(
            "/forgot",
            data={"email": "ada@example.com", "_csrf": self.csrf_of(ada)},
            follow_redirects=False,
        )
        self.assertEqual(sent.status_code, 200)
        self.assertEqual(self.account(ada).status_code, 200)

    def test_a_reset_from_the_signed_in_browser_does_not_keep_it_signed_in(self):
        self.write_user("ada@example.com", "correct-horse")
        ada = self.client()
        self.sign_in(ada, "ada@example.com", "correct-horse")
        token = sotto.new_token("ada@example.com", "reset", 3600)
        saved = ada.post(
            "/reset/" + token,
            data={"new": "new-password-1", "_csrf": self.csrf_of(ada)},
            follow_redirects=False,
        )
        self.assertEqual(saved.status_code, 200)
        self.assertIn(b"Your password is set.", saved.data)
        self.assertNotIn(b"log out", saved.data)
        self.assertEqual(self.account(ada).status_code, 302)

    def api_token(self, email, password):
        created = self.client().post(
            "/api/v1/token",
            json={"email": email, "password": password, "label": "phone"},
        )
        self.assertEqual(created.status_code, 201)
        return created.get_json()["token"]

    def api_me(self, token):
        return self.client().get(
            "/api/v1/me",
            headers={"Authorization": "Bearer " + token},
        )

    def test_log_out_and_password_change_leave_api_tokens_valid(self):
        self.write_user("ada@example.com", "correct-horse")
        token = self.api_token("ada@example.com", "correct-horse")
        self.assertEqual(self.api_me(token).status_code, 200)
        web = self.client()
        self.sign_in(web, "ada@example.com", "correct-horse")
        self.assertEqual(self.log_out(web).status_code, 302)
        self.assertEqual(self.api_me(token).status_code, 200)
        self.sign_in(web, "ada@example.com", "correct-horse")
        changed = self.change_password(web, "correct-horse", "new-password-1")
        self.assertIn(b"Password changed.", changed.data)
        self.assertEqual(self.api_me(token).status_code, 200)
        self.assertEqual(self.api_me(token).get_json()["email"], "ada@example.com")

    def test_deleting_an_account_does_not_change_its_session_or_api_token(self):
        self.write_user("ada@example.com", "correct-horse")
        self.write_user("admin@example.com", "admin-password-1", admin=True)
        ada = self.client()
        self.sign_in(ada, "ada@example.com", "correct-horse")
        token = self.api_token("ada@example.com", "correct-horse")
        admin = self.client()
        self.sign_in(admin, "admin@example.com", "admin-password-1")
        deleted = admin.post(
            "/admin/delete",
            data={"username": "ada@example.com", "_csrf": self.csrf_of(admin)},
            follow_redirects=False,
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertIn(b"Deleted account", deleted.data)
        home = ada.get("/", follow_redirects=False)
        self.assertEqual(home.status_code, 200)
        self.assertIn(b"log out", home.data)
        self.assertEqual(self.api_me(token).status_code, 200)
        self.assertEqual(admin.get("/admin", follow_redirects=False).status_code, 200)

    def test_deleting_an_account_must_not_revive_a_session_logout_already_rejected(self):
        self.write_user("ada@example.com", "correct-horse")
        self.write_user("admin@example.com", "admin-password-1", admin=True)
        ada = self.client()
        stale = self.client()
        self.sign_in(ada, "ada@example.com", "correct-horse")
        self.sign_in(stale, "ada@example.com", "correct-horse")
        self.assertEqual(self.log_out(ada).status_code, 302)
        rejected = stale.get("/", follow_redirects=False)
        self.assertEqual(rejected.status_code, 302)
        self.assertTrue(rejected.headers["Location"].startswith("/login"))
        admin = self.client()
        self.sign_in(admin, "admin@example.com", "admin-password-1")
        deleted = admin.post(
            "/admin/delete",
            data={"username": "ada@example.com", "_csrf": self.csrf_of(admin)},
            follow_redirects=False,
        )
        self.assertEqual(deleted.status_code, 200)
        revived = stale.get("/", follow_redirects=False)
        self.assertNotEqual(revived.status_code, 200)
        self.assertNotIn(b"log out", revived.data)

    def test_unreadable_users_file_must_not_accept_a_mismatched_generation(self):
        self.write_user("ada@example.com", "correct-horse", session_generation=4)
        client = self.client()
        with client.session_transaction() as sess:
            sess["user"] = "ada@example.com"
            sess["session_generation"] = 1
        rejected = self.account(client)
        self.assertEqual(rejected.status_code, 302)
        with open(sotto.USERS_PATH, "w") as f:
            f.write("{not-json")
        revived = self.account(client)
        self.assertNotEqual(revived.status_code, 200)
        self.assertNotIn(b"log out", revived.data)

    def test_recreating_an_account_returns_it_to_the_starting_generation(self):
        self.write_user("ada@example.com", "correct-horse")
        self.write_user("admin@example.com", "admin-password-1", admin=True)
        first = self.client()
        self.sign_in(first, "ada@example.com", "correct-horse")
        self.assertEqual(self.log_out(first).status_code, 302)
        admin = self.client()
        self.sign_in(admin, "admin@example.com", "admin-password-1")
        deleted = admin.post(
            "/admin/delete",
            data={"username": "ada@example.com", "_csrf": self.csrf_of(admin)},
            follow_redirects=False,
        )
        self.assertIn(b"Deleted account", deleted.data)
        created = admin.post(
            "/admin/add",
            data={"username": "ada@example.com", "_csrf": self.csrf_of(admin)},
            follow_redirects=False,
        )
        self.assertIn(b"Created ada@example.com", created.data)
        self.write_user("ada@example.com", "correct-horse")
        ada = self.client()
        self.sign_in(ada, "ada@example.com", "correct-horse")
        with ada.session_transaction() as sess:
            self.assertEqual(sess.get("session_generation"), 0)
        admin.post(
            "/admin/delete",
            data={"username": "ada@example.com", "_csrf": self.csrf_of(admin)},
            follow_redirects=False,
        )
        home = ada.get("/", follow_redirects=False)
        self.assertEqual(home.status_code, 200)
        self.assertIn(b"log out", home.data)


if __name__ == "__main__":
    unittest.main()
