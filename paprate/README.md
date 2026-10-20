# PapRate Telegram Bot

Bot rating foto sukarela untuk komunitas dewasa dengan moderasi manual sebelum publikasi. Bot ini hanya menargetkan foto non-eksplisit; tidak menerima konten telanjang/eksplisit, foto anak, atau foto tanpa persetujuan orang yang ditampilkan.

## Fitur
- Persetujuan pengguna 18+ sebelum memakai bot (deklarasi, bukan verifikasi identitas).
- Foto dikirim lewat chat pribadi dan masuk antrean admin; tidak otomatis terbit.
- Rating 1–10, satu rating per akun/foto, anti-rating foto sendiri, dan rate limit.
- Tombol laporan; foto disembunyikan saat ambang laporan tercapai.
- Hapus kiriman sendiri, blokir akun oleh admin, statistik, SQLite, dan penyimpanan persisten.
- Token bot hanya berasal dari environment variable; file .env dikecualikan Git.

## Deployment
1. Buat bot melalui @BotFather dan simpan token sebagai secret BOT_TOKEN.
2. Buat channel Telegram secara manual. Tambahkan bot sebagai admin dengan izin Post Messages dan Delete Messages.
3. Isi environment variables: BOT_TOKEN, ADMIN_IDS (Telegram numeric user ID, pisahkan dengan koma), RATINGS_CHANNEL_ID (ID -100... atau @username channel publik), dan DATABASE_PATH=/data/paprate.sqlite3.
4. Tambahkan volume persisten yang dipasang di /data.
5. Untuk Railway, hubungkan repository ke service dan atur Root Directory menjadi /paprate; gunakan Dockerfile.
6. Admin perlu membuka chat bot dan mengirim /start agar notifikasi pribadi dapat diterima.

Bot API tidak dapat membuat channel Telegram sendiri. Channel harus dibuat dari akun Telegram, lalu bot diberi izin admin. Token jangan dimasukkan ke source code, issue, chat, atau file yang di-commit.

## Perintah
Pengguna: /start, /help, /rules, /submit, /cancel, /delete_my_photo.
Admin: /pending, /stats, /block_user USER_ID, /unblock_user USER_ID.

## Menjalankan lokal
Python 3.11+ direkomendasikan:
- Buat virtual environment Python.
- Jalankan pip install -r requirements.txt.
- Salin .env.example menjadi .env, lalu isi konfigurasi sebenarnya.
- Jalankan python bot.py.

## Batas keamanan
Persetujuan tombol bukan verifikasi identitas atau bukti izin foto. Admin tetap harus memeriksa bahwa foto dikirim sukarela oleh orang dewasa yang memiliki hak/izin. Jangan menerima foto intim eksplisit, foto anak, atau foto tanpa consent. Simpan ID Telegram dan database secara aman, batasi akses hosting, dan rotasi token jika bocor.
