from flask_bcrypt import Bcrypt
from app4 import app, get_db_connection

bcrypt = Bcrypt(app)

NEW_PASSWORD = "admin"  # ← choose your password

with app.app_context():
    conn = get_db_connection()
    cursor = conn.cursor()

    hashed = bcrypt.generate_password_hash(NEW_PASSWORD).decode("utf-8")

    cursor.execute(
        """
        UPDATE users
        SET password = %s
        WHERE email = 'connect.aiindia@gmail.com'
        """,
        (hashed,),
    )

    conn.commit()
    cursor.close()
    conn.close()

print("✅ Admin password reset successfully")
