(() => {
  const start = document.getElementById('start');
  const about = document.getElementById('about');
  const demoSend = document.getElementById('demoSend');
  const notice = document.querySelector('.notice');
  start?.addEventListener('click', () => {
    notice?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    if (notice) notice.setAttribute('tabindex', '-1');
    notice?.focus({ preventScroll: true });
  });
  about?.addEventListener('click', () => {
    alert('NEXA Social adalah fondasi aplikasi percakapan. Untuk akun, pesan antarperangkat, dan sinkronisasi, server publik harus dikonfigurasi terlebih dahulu.');
  });
  demoSend?.addEventListener('click', () => {
    alert('Ini hanya pratinjau. Pesan online belum aktif karena URL server NEXA belum dikonfigurasi.');
  });
})();