"""
Sets the password of a desk admin from the terminal.

If the user doesn't exist, the script creates it with the Admin role. If it
exists, the script sets the new password, gives it the Admin role, activates
it and logs it out everywhere. Use it after the install, or when an admin
forgets the password. The server can run at the same time.

Run from the project root:

    make set-admin-password                  # user "admin"
    make set-admin-password ADMIN_USER=priya   # another user

On Windows: .\\run.ps1 set-admin-password [username]
"""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import auth  # noqa: E402
import store  # noqa: E402


def read_password() -> str:
    if not sys.stdin.isatty():
        sys.exit("Run this command in a terminal: it asks for the password.")
    password = getpass.getpass("New password: ")
    if len(password) < auth.PASSWORD_MIN:
        sys.exit(f"Use a password of at least {auth.PASSWORD_MIN} characters.")
    if len(password) > auth.PASSWORD_MAX:
        sys.exit(f"Keep the password under {auth.PASSWORD_MAX} characters.")
    if getpass.getpass("Type it again: ") != password:
        sys.exit("The passwords are not the same. Nothing changed.")
    return password


def main() -> None:
    username = (sys.argv[1] if len(sys.argv) > 1 else "admin").strip().lower()
    if not auth.USERNAME.fullmatch(username):
        sys.exit(
            "Use 2–32 lowercase letters, digits, dots, dashes or underscores "
            "for the username."
        )
    auth.seed_roles()
    password_hash = auth.hash_password(read_password())
    admin_role_id = store.find_role(auth.ADMIN_ROLE)["id"]
    found = store.find_user_login(username)
    if not found:
        store.add_user(username, "Administrator", password_hash, admin_role_id)
        print(f"Created the admin '{username}' with the new password.")
        return
    user_id = found[0]
    user = store.get_user(user_id)
    store.set_password_hash(user_id, password_hash)
    store.update_user(user_id, username, user["name"], admin_role_id, active=True)
    store.delete_user_sessions(user_id)
    print(f"Set the new password for '{username}'. Its old logins are closed.")


if __name__ == "__main__":
    main()
