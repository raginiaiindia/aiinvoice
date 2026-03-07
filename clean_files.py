import os
from datetime import datetime, timedelta
from db import get_db_connection  # adjust import


def cleanup_old_files():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT id, file_path
        FROM extraction_history
        WHERE timestamp < NOW() - INTERVAL 15 DAY
          AND file_path IS NOT NULL
    """
    )

    rows = cursor.fetchall()

    for row in rows:
        file_path = row["file_path"]

        # delete file only
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

        # keep row, just clear file reference
        cursor.execute(
            "UPDATE extraction_history SET file_path = NULL WHERE id = %s", (row["id"],)
        )

    conn.commit()
    cursor.close()
    conn.close()
