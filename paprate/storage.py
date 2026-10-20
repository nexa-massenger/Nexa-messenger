"""SQLite persistence for PapRate."""
from __future__ import annotations
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

class Store:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @contextmanager
    def db(self):
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self):
        with self.db() as db:
            if self.path != ":memory:": db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, consent INTEGER NOT NULL DEFAULT 0, blocked INTEGER NOT NULL DEFAULT 0, awaiting INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS photos(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, file_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', channel_id TEXT, message_id INTEGER, created INTEGER NOT NULL, FOREIGN KEY(user_id) REFERENCES users(user_id));
            CREATE INDEX IF NOT EXISTS photos_user_idx ON photos(user_id,status);
            CREATE TABLE IF NOT EXISTS ratings(photo_id INTEGER NOT NULL, user_id INTEGER NOT NULL, score INTEGER NOT NULL CHECK(score BETWEEN 1 AND 10), created INTEGER NOT NULL, UNIQUE(photo_id,user_id), FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS reports(photo_id INTEGER NOT NULL, user_id INTEGER NOT NULL, created INTEGER NOT NULL, UNIQUE(photo_id,user_id), FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE);
            """)

    def run(self, sql, args=(), one=False, all_rows=False):
        with self.db() as db:
            cur = db.execute(sql, args)
            if one: return cur.fetchone()
            if all_rows: return cur.fetchall()
            return cur.rowcount

    def ensure(self, uid): self.run("INSERT OR IGNORE INTO users VALUES(?,0,0,0,?)", (uid, int(time.time())))
    def user(self, uid): return self.run("SELECT * FROM users WHERE user_id=?", (uid,), one=True)
    def consent(self, uid): self.run("UPDATE users SET consent=1 WHERE user_id=?", (uid,))
    def awaiting(self, uid, value): self.run("UPDATE users SET awaiting=? WHERE user_id=?", (int(value), uid))
    def block(self, uid, value):
        self.ensure(uid); self.run("UPDATE users SET blocked=?,awaiting=0 WHERE user_id=?", (int(value),uid))
    def add_photo(self, uid, file_id):
        now = int(time.time())
        with self.db() as db:
            cur = db.execute("INSERT INTO photos(user_id,file_id,status,created) VALUES(?,?,'pending',?)", (uid, file_id, now))
            db.execute("UPDATE users SET awaiting=0 WHERE user_id=?", (uid,))
            return int(cur.lastrowid)
    def photo(self, pid): return self.run("SELECT * FROM photos WHERE id=?", (pid,), one=True)
    def pending(self, limit=10): return self.run("SELECT * FROM photos WHERE status='pending' ORDER BY created LIMIT ?", (max(1,min(limit,20)),), all_rows=True)
    def count(self, table, uid, since): return int(self.run(f"SELECT COUNT(*) n FROM {table} WHERE user_id=? AND created>=?", (uid,since), one=True)["n"])
    def claim(self, pid): return self.run("UPDATE photos SET status='publishing' WHERE id=? AND status='pending'", (pid,)) == 1
    def reject(self, pid): return self.run("UPDATE photos SET status='rejected' WHERE id=? AND status='pending'", (pid,)) == 1
    def publish(self, pid, chat_id, msg_id): self.run("UPDATE photos SET status='approved',channel_id=?,message_id=? WHERE id=? AND status='publishing'", (str(chat_id),msg_id,pid))
    def rollback_publish(self, pid): self.run("UPDATE photos SET status='pending' WHERE id=? AND status='publishing'", (pid,))
    def rate(self, pid, uid, score):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            photo=db.execute("SELECT user_id,status FROM photos WHERE id=?",(pid,)).fetchone()
            if not photo or photo["status"] != "approved": return ("unavailable",None,0)
            if photo["user_id"] == uid: return ("own",None,0)
            try: db.execute("INSERT INTO ratings VALUES(?,?,?,?)",(pid,uid,score,int(time.time())))
            except sqlite3.IntegrityError: return ("duplicate",None,0)
            row=db.execute("SELECT AVG(score) avg,COUNT(*) n FROM ratings WHERE photo_id=?",(pid,)).fetchone()
            return ("ok",float(row["avg"]),int(row["n"]))
    def report(self,pid,uid,threshold=3):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM photos WHERE id=? AND status='approved'",(pid,)).fetchone()
            if not row: return ("unavailable",0,False,None)
            try: db.execute("INSERT INTO reports VALUES(?,?,?)",(pid,uid,int(time.time())))
            except sqlite3.IntegrityError: return ("duplicate",0,False,dict(row))
            count=int(db.execute("SELECT COUNT(*) FROM reports WHERE photo_id=?",(pid,)).fetchone()[0])
            hidden = count >= threshold and db.execute("UPDATE photos SET status='hidden' WHERE id=? AND status='approved'",(pid,)).rowcount == 1
            fresh=db.execute("SELECT * FROM photos WHERE id=?",(pid,)).fetchone()
            return ("ok",count,hidden,dict(fresh))
    def user_photos(self,uid): return self.run("SELECT * FROM photos WHERE user_id=? AND status IN ('pending','approved','hidden','rejected') ORDER BY id DESC",(uid,),all_rows=True)
    def delete_user_photos(self,uid):
        self.run("UPDATE users SET awaiting=0 WHERE user_id=?",(uid,))
        return self.run("DELETE FROM photos WHERE user_id=?",(uid,))
    def stats(self):
        return {s:int(self.run("SELECT COUNT(*) FROM photos WHERE status=?",(s,),one=True)[0]) for s in ("pending","approved","hidden")} | {"ratings":int(self.run("SELECT COUNT(*) FROM ratings",one=True)[0]),"reports":int(self.run("SELECT COUNT(*) FROM reports",one=True)[0])}
