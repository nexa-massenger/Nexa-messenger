"""PapRate Telegram bot: opt-in, moderated photo ratings for adults."""
from __future__ import annotations

import logging
import os
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.constants import ChatType
from telegram.error import TelegramError, BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv
from storage import Store

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("paprate")


def positive_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} harus berupa angka.") from exc
    if value < minimum:
        raise RuntimeError(f"{name} minimal {minimum}.")
    return value


def admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_IDS", "")
    try:
        ids = {int(x.strip()) for x in raw.split(",") if x.strip()}
    except ValueError as exc:
        raise RuntimeError("ADMIN_IDS harus berisi Telegram numeric user ID dipisah koma.") from exc
    if not ids or any(x <= 0 for x in ids):
        raise RuntimeError("Isi ADMIN_IDS dengan minimal satu ID Telegram numerik positif.")
    return ids


def channel_target() -> int | str:
    raw = os.getenv("RATINGS_CHANNEL_ID", "").strip()
    if not raw:
        raise RuntimeError("RATINGS_CHANNEL_ID wajib diisi.")
    try:
        return int(raw)
    except ValueError:
        if raw.startswith("@") and len(raw) > 1:
            return raw
        raise RuntimeError("RATINGS_CHANNEL_ID harus ID numerik channel (-100...) atau @username publik.")


TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError("BOT_TOKEN belum diatur; masukkan sebagai environment secret.")
ADMINS = admin_ids()
CHANNEL = channel_target()
DB_PATH = os.getenv("DATABASE_PATH", "./data/paprate.sqlite3").strip() or "./data/paprate.sqlite3"
MAX_SUBMISSIONS = positive_int("MAX_SUBMISSIONS_PER_DAY", 3)
MAX_RATINGS = positive_int("MAX_RATINGS_PER_HOUR", 15)
MAX_REPORTS = positive_int("MAX_REPORTS_PER_DAY", 5)
REPORT_THRESHOLD = positive_int("REPORT_HIDE_THRESHOLD", 3, 2)
COOLDOWN = positive_int("SUBMISSION_COOLDOWN_SECONDS", 120, 0)

RULES = (
    "📜 ATURAN PAPRATE\n\n"
    "• Khusus pengguna 18 tahun ke atas; persetujuan usia adalah deklarasi, bukan verifikasi identitas.\n"
    "• Kirim hanya foto diri sendiri atau foto yang semua orang di dalamnya sudah memberi izin.\n"
    "• Dilarang foto telanjang/eksplisit, foto anak, foto tanpa izin, doxxing, ancaman, atau pelecehan.\n"
    "• Rating 1–10; komentar dan interaksi harus sopan.\n"
    "• Semua foto ditinjau admin sebelum terbit. Caption pengirim tidak dipublikasikan.\n"
    "• /delete_my_photo meminta penghapusan kirimanmu yang masih tercatat.\n\n"
    "Dengan menekan tombol persetujuan, kamu menyatakan berusia 18+ dan setuju pada aturan."
)

store = Store(DB_PATH)


def kb_consent(): return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Saya 18+ dan setuju", callback_data="consent")]])
def kb_mod(pid): return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Terbitkan", callback_data=f"mod:yes:{pid}"), InlineKeyboardButton("❌ Tolak", callback_data=f"mod:no:{pid}")]])
def kb_rate(pid):
    return InlineKeyboardMarkup([[InlineKeyboardButton(str(i), callback_data=f"rate:{pid}:{i}") for i in range(start, start + 5)] for start in (1, 6)] + [[InlineKeyboardButton("🚩 Laporkan", callback_data=f"report:{pid}")]])


def allowed(uid):
    user = store.user(uid)
    if not user: return False, "start"
    if user["blocked"]: return False, "blocked"
    if not user["consent"]: return False, "consent"
    return True, "ok"


def private(update): return bool(update.effective_chat and update.effective_chat.type == ChatType.PRIVATE)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not private(update): return
    uid = update.effective_user.id
    store.ensure(uid)
    ok, reason = allowed(uid)
    if reason == "blocked":
        await update.message.reply_text("Akses akun ini dibatasi.")
        return
    if not ok:
        await update.message.reply_text("Selamat datang. Baca aturan berikut sebelum menggunakan bot:\n\n" + RULES, reply_markup=kb_consent())
        return
    await update.message.reply_text("Kamu sudah terdaftar. Gunakan /submit untuk mengirim foto, /rules untuk aturan, atau /delete_my_photo untuk menghapus kiriman.")


async def rules_cmd(update, context):
    if update.message: await update.message.reply_text(RULES)


async def help_cmd(update, context):
    if update.message:
        await update.message.reply_text("/start — mulai dan persetujuan 18+\n/submit — kirim foto untuk moderasi\n/cancel — batalkan kiriman\n/rules — aturan\n/delete_my_photo — hapus kiriman\n\nAdmin: /pending, /stats, /block_user ID, /unblock_user ID")


async def submit(update, context):
    if not update.message or not update.effective_user or not private(update): return
    uid = update.effective_user.id
    store.ensure(uid)
    ok, reason = allowed(uid)
    if not ok:
        await update.message.reply_text("Akses dibatasi." if reason == "blocked" else "Ketik /start lalu setujui aturan terlebih dahulu.")
        return
    now = int(time.time())
    day = now - now % 86400
    if store.count("photos", uid, day) >= MAX_SUBMISSIONS:
        await update.message.reply_text(f"Batas {MAX_SUBMISSIONS} foto per hari tercapai.")
        return
    if COOLDOWN and store.count("photos", uid, now - COOLDOWN):
        await update.message.reply_text(f"Tunggu {COOLDOWN} detik sebelum mengirim lagi.")
        return
    store.awaiting(uid, True)
    await update.message.reply_text("Kirim satu foto sekarang sebagai foto Telegram biasa. Caption tidak dipublikasikan. Admin akan memeriksa foto sebelum tayang. /cancel untuk batal.")


async def cancel(update, context):
    if update.message and update.effective_user:
        store.awaiting(update.effective_user.id, False)
        await update.message.reply_text("Mode kirim foto dibatalkan.")


async def receive_photo(update, context):
    if not update.message or not update.effective_user or not private(update): return
    uid = update.effective_user.id
    ok, reason = allowed(uid)
    user = store.user(uid)
    if not ok or not user or not user["awaiting"]:
        await update.message.reply_text("Ketik /start dan /submit terlebih dahulu.")
        return
    pid = store.add_photo(uid, update.message.photo[-1].file_id)
    sent = 0
    for aid in ADMINS:
        try:
            await context.bot.send_photo(aid, update.message.photo[-1].file_id, caption=f"Kiriman #{pid} menunggu moderasi. ID pengirim: {uid}", reply_markup=kb_mod(pid))
            sent += 1
        except TelegramError as exc:
            log.warning("Notifikasi admin gagal (%s)", type(exc).__name__)
    await update.message.reply_text(f"Foto #{pid} masuk antrean moderasi; belum ditayangkan." if sent else "Foto tersimpan, tetapi admin belum mendapat notifikasi. Admin perlu membuka chat bot.")


async def pending_cmd(update, context):
    if not update.message or not update.effective_user or not private(update): return
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("Khusus admin.")
        return
    rows = store.pending()
    if not rows:
        await update.message.reply_text("Antrean kosong.")
        return
    for row in rows:
        try:
            await context.bot.send_photo(update.effective_user.id, row["file_id"], caption=f"Kiriman #{row['id']} menunggu moderasi. ID pengirim: {row['user_id']}", reply_markup=kb_mod(row["id"]))
        except TelegramError:
            pass


async def stats_cmd(update, context):
    if not update.message or not update.effective_user or not private(update): return
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("Khusus admin.")
        return
    s = store.stats()
    await update.message.reply_text("Statistik\n" + "\n".join(f"{k}: {v}" for k, v in s.items()))


async def block_cmd(update, context, blocked):
    if not update.message or not update.effective_user or not private(update): return
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("Khusus admin.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("Format: /block_user USER_ID" if blocked else "Format: /unblock_user USER_ID")
        return
    try:
        target = int(context.args[0])
        if target <= 0 or target in ADMINS: raise ValueError
    except ValueError:
        await update.message.reply_text("ID tidak valid; akun admin tidak dapat diblokir.")
        return
    store.block(target, blocked)
    await update.message.reply_text(f"User {target} {'diblokir' if blocked else 'dibuka blokirnya'}.")


async def block_user(update, context): await block_cmd(update, context, True)
async def unblock_user(update, context): await block_cmd(update, context, False)


async def delete_cmd(update, context):
    if not update.message or not update.effective_user or not private(update): return
    ok, reason = allowed(update.effective_user.id)
    if not ok:
        await update.message.reply_text("Ketik /start terlebih dahulu.")
        return
    rows = store.user_photos(update.effective_user.id)
    if not rows:
        await update.message.reply_text("Tidak ada kiriman yang tercatat.")
        return
    await update.message.reply_text(f"Hapus {len(rows)} kiriman yang tercatat?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Ya, hapus", callback_data="delete:yes"), InlineKeyboardButton("Batal", callback_data="delete:no")]]))


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data: return
    uid = q.from_user.id
    data = q.data
    store.ensure(uid)
    if data == "consent":
        if not q.message or q.message.chat.type != ChatType.PRIVATE:
            await q.answer("Buka chat pribadi bot.", show_alert=True)
            return
        store.consent(uid)
        await q.answer("Persetujuan disimpan.")
        await q.edit_message_text("Persetujuan tersimpan. Gunakan /submit untuk mengirim foto.")
        return
    if data == "delete:no":
        await q.answer("Dibatalkan.")
        await q.edit_message_text("Penghapusan dibatalkan.")
        return
    if data == "delete:yes":
        if not q.message or q.message.chat.type != ChatType.PRIVATE:
            await q.answer("Buka chat pribadi bot.", show_alert=True)
            return
        rows = store.user_photos(uid)
        failed = 0
        for row in rows:
            if row["status"] in ("approved", "hidden") and row["channel_id"] and row["message_id"]:
                try:
                    await context.bot.delete_message(int(row["channel_id"]), int(row["message_id"]))
                except BadRequest as exc:
                    if "message to delete not found" not in str(exc).lower(): failed += 1
                except TelegramError:
                    failed += 1
        if failed:
            await q.answer("Sebagian foto gagal dihapus; cek izin bot.", show_alert=True)
            return
        n = store.delete_user_photos(uid)
        await q.answer("Terhapus.")
        await q.edit_message_text(f"Selesai. {n} kiriman serta rating/laporan terkait terhapus dari database bot.")
        return
    if data.startswith("mod:"):
        if uid not in ADMINS:
            await q.answer("Khusus admin.", show_alert=True)
            return
        parts = data.split(":")
        pid = int(parts[2]) if len(parts) == 3 and parts[2].isdigit() else 0
        photo = store.photo(pid)
        if not photo or photo["status"] != "pending":
            await q.answer("Kiriman sudah diproses.", show_alert=True)
            return
        if parts[1] == "no":
            store.reject(pid)
            await q.answer("Ditolak.")
            await q.edit_message_caption(f"Kiriman #{pid} ditolak.", reply_markup=None)
            return
        if parts[1] != "yes" or not store.claim(pid):
            await q.answer("Tidak bisa memproses kiriman.", show_alert=True)
            return
        try:
            post = await context.bot.send_photo(CHANNEL, photo["file_id"], caption=f"📸 RATE PAP #{pid}\n\nNilai 1–10. Tetap sopan. Kiriman harus sukarela dan non-eksplisit.", reply_markup=kb_rate(pid))
            store.publish(pid, post.chat.id, post.message_id)
            await q.answer("Diterbitkan.")
            await q.edit_message_caption(f"Kiriman #{pid} disetujui dan tayang.", reply_markup=None)
            try:
                await context.bot.send_message(photo["user_id"], f"Foto #{pid} disetujui dan tayang di channel.")
            except TelegramError:
                pass
        except TelegramError as exc:
            store.rollback_publish(pid)
            log.error("Publikasi gagal (%s)", type(exc).__name__)
            await q.answer("Gagal terbit; periksa izin bot dan ID channel.", show_alert=True)
        return
    if data.startswith("rate:"):
        p = data.split(":")
        if len(p) != 3 or not p[1].isdigit() or not p[2].isdigit():
            await q.answer("Rating tidak valid.", show_alert=True)
            return
        pid, score = int(p[1]), int(p[2])
        photo = store.photo(pid)
        if score not in range(1, 11) or not q.message or not photo or photo["status"] != "approved" or str(q.message.chat.id) != str(photo["channel_id"]) or q.message.message_id != photo["message_id"]:
            await q.answer("Foto tidak tersedia.", show_alert=True)
            return
        ok, reason = allowed(uid)
        if not ok:
            await q.answer("Ketik /start dan setujui aturan di chat pribadi." if reason != "blocked" else "Akses dibatasi.", show_alert=True)
            return
        if store.count("ratings", uid, int(time.time()) - 3600) >= MAX_RATINGS:
            await q.answer("Batas rating per jam tercapai.", show_alert=True)
            return
        result, avg, count = store.rate(pid, uid, score)
        if result == "ok": await q.answer(f"Nilai {score}/10 tercatat. Rata-rata {avg:.1f} dari {count} suara.")
        elif result == "own": await q.answer("Tidak bisa memberi nilai pada foto sendiri.", show_alert=True)
        elif result == "duplicate": await q.answer("Kamu sudah memberi nilai.", show_alert=True)
        else: await q.answer("Foto tidak tersedia.", show_alert=True)
        return
    if data.startswith("report:"):
        p = data.split(":")
        pid = int(p[1]) if len(p) == 2 and p[1].isdigit() else 0
        photo = store.photo(pid)
        if not q.message or not photo or photo["status"] != "approved" or str(q.message.chat.id) != str(photo["channel_id"]) or q.message.message_id != photo["message_id"]:
            await q.answer("Foto tidak tersedia.", show_alert=True)
            return
        ok, reason = allowed(uid)
        if not ok:
            await q.answer("Ketik /start dan setujui aturan di chat pribadi." if reason != "blocked" else "Akses dibatasi.", show_alert=True)
            return
        if store.count("reports", uid, int(time.time()) - 86400) >= MAX_REPORTS:
            await q.answer("Batas laporan hari ini tercapai.", show_alert=True)
            return
        result, count, hidden, fresh = store.report(pid, uid, REPORT_THRESHOLD)
        if result != "ok":
            await q.answer("Sudah dilaporkan atau tidak tersedia.", show_alert=True)
            return
        if hidden:
            try:
                await context.bot.delete_message(int(fresh["channel_id"]), fresh["message_id"])
            except TelegramError as exc:
                log.warning("Auto-hide gagal (%s)", type(exc).__name__)
            for aid in ADMINS:
                try: await context.bot.send_message(aid, f"Foto #{pid} disembunyikan karena laporan ({count}). Mohon tinjau.")
                except TelegramError: pass
        await q.answer("Laporan diterima. Terima kasih.")
        return
    await q.answer("Aksi tidak dikenal.")


async def post_init(app: Application):
    await app.bot.set_my_commands([BotCommand("start", "Mulai / setujui aturan"), BotCommand("help", "Bantuan"), BotCommand("rules", "Aturan"), BotCommand("submit", "Kirim foto"), BotCommand("cancel", "Batalkan"), BotCommand("delete_my_photo", "Hapus kiriman")])
    log.info("PapRate siap polling. Pastikan bot sudah menjadi admin channel.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Update gagal (%s)", type(context.error).__name__ if context.error else "unknown")


def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    for cmd, fn in [("start", start), ("help", help_cmd), ("rules", rules_cmd), ("submit", submit), ("cancel", cancel), ("pending", pending_cmd), ("stats", stats_cmd), ("delete_my_photo", delete_cmd), ("block_user", block_user), ("unblock_user", unblock_user)]:
        app.add_handler(CommandHandler(cmd, fn))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, receive_photo))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_error_handler(on_error)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
