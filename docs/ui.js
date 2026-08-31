/* 사이드바 셸 동작 — 스크롤 스파이와 테마 전환.
   SnowUI Shell.jsx 의 구조를 따른다: 레일 선택 표시, 탑바 브레드크럼, 테마 토글.
   테마는 <html data-theme> 로 두고 색은 전부 CSS 토큰이 처리한다. */
(function () {
  var rows = Array.prototype.slice.call(document.querySelectorAll('.rail-row[href^="#"]'));
  var crumb = document.getElementById('crumb-cur');
  var scroll = document.querySelector('.scroll');

  function mark(id) {
    rows.forEach(function (a) {
      var on = a.getAttribute('href') === '#' + id;
      a.classList.toggle('on', on);
      if (on && crumb) crumb.textContent = a.textContent.trim();
    });
  }

  // 화면 상단 1/3 지점을 지나는 마지막 섹션을 현재로 본다
  var secs = rows
    .map(function (a) { return document.querySelector(a.getAttribute('href')); })
    .filter(Boolean);
  function spy() {
    var cur;
    // 맨 아래에서는 마지막 섹션이 1/3 선까지 올라올 수 없다. 바닥이면 마지막을 쓴다.
    if (scroll.scrollTop + scroll.clientHeight >= scroll.scrollHeight - 4) {
      cur = secs[secs.length - 1];
    } else {
      var line = scroll.scrollTop + scroll.clientHeight / 3;
      cur = secs[0];
      secs.forEach(function (el) { if (el.offsetTop <= line) cur = el; });
    }
    if (cur) mark(cur.id);
  }
  if (scroll) { scroll.addEventListener('scroll', spy, { passive: true }); spy(); }

  rows.forEach(function (a) {
    a.addEventListener('click', function (e) {
      var el = document.querySelector(a.getAttribute('href'));
      if (!el) return;
      e.preventDefault();
      scroll.scrollTo({ top: el.offsetTop - 12, behavior: 'smooth' });
    });
  });

  // 테마 — 선택은 브라우저에만 남는다. 접근 불가한 환경도 있으므로 감싼다.
  var root = document.documentElement;
  var btn = document.getElementById('theme-btn');
  try {
    var saved = localStorage.getItem('theme');
    if (saved) root.setAttribute('data-theme', saved);
  } catch (e) { /* 저장소 접근 불가 — 기본값(dark) 유지 */ }
  if (btn) {
    btn.addEventListener('click', function () {
      var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('theme', next); } catch (e) { /* 무시 */ }
      window.dispatchEvent(new Event('resize'));   // 캔버스 색 즉시 갱신
    });
  }
})();
