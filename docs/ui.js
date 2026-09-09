/* ═══════════════════════════════════════════════════════════════════════
   SnowUI Shell Controller — 스크롤 스파이, 스무스 이동 및 테마 토글 v7.1
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
  // 1. 브라우저의 임의 스크롤 복원 원천 차단
  if ('scrollRestoration' in history) {
    history.scrollRestoration = 'manual';
  }

  // 2. URL 주소창 잔류 해시(#s-scenario 등) 즉시 청소 (새로고침 시 앵커 튀김 방지)
  if (location.hash) {
    try {
      history.replaceState(null, '', location.pathname + location.search);
    } catch (e) {}
  }

  var scroll = document.querySelector('.scroll');
  var crumb = document.getElementById('crumb-cur');
  var rows = Array.prototype.slice.call(document.querySelectorAll('.rail-row[href*="#"]'));

  var isManualClick = false;
  var clickTimer = null;
  var currentActiveId = null;

  // 스크롤 컨테이너 초기화 (즉각 0 고정)
  if (scroll) {
    scroll.style.scrollBehavior = 'auto';
    scroll.scrollTop = 0;
  }
  window.scrollTo(0, 0);

  // 뒤로가기/BFCache/새로고침 시점에도 스크롤 복원 차단 및 0 고정
  window.addEventListener('pageshow', function () {
    if (scroll) {
      scroll.style.scrollBehavior = 'auto';
      scroll.scrollTop = 0;
    }
    window.scrollTo(0, 0);
  });

  function getTargetId(a) {
    var href = a.getAttribute('href') || '';
    var hashIndex = href.indexOf('#');
    return hashIndex !== -1 ? href.substring(hashIndex + 1) : null;
  }

  // 현재 페이지의 로컬 해시 링크만 필터링 (외래 페이지 제외)
  var currentPath = (location.pathname.split('/').pop() || 'index.html').split('?')[0];
  var localRows = rows.filter(function (a) {
    var href = a.getAttribute('href') || '';
    var hashIndex = href.indexOf('#');
    if (hashIndex === -1) return false;
    var pathPart = href.substring(0, hashIndex).split('?')[0];
    if (pathPart && pathPart !== currentPath) {
      return false;
    }
    var tid = href.substring(hashIndex + 1);
    return tid && document.getElementById(tid);
  });

  function mark(id) {
    if (!id) return;
    currentActiveId = id;
    rows.forEach(function (a) {
      var tid = getTargetId(a);
      var on = tid === id;
      a.classList.toggle('on', on);
      if (on && crumb) {
        var label = a.textContent.trim().replace(/^[0-9.]+\s*/, '').replace(/\s*↗$/, '');
        crumb.textContent = label;
      }
    });
  }

  // 카드 클릭 시 네온 발광 효과 (같은 행 다른 열이어도 사용자가 정확히 인지)
  function highlightCard(el) {
    document.querySelectorAll('.card-target-active').forEach(function (p) {
      p.classList.remove('card-target-active');
    });
    var targets = [];
    if (el.classList.contains('panel')) {
      targets.push(el);
    } else {
      var panels = el.querySelectorAll('.panel');
      if (panels.length > 0) {
        targets = Array.prototype.slice.call(panels);
      } else {
        targets.push(el);
      }
    }
    targets.forEach(function (t) {
      void t.offsetWidth; // 리플로우 강제 트리거로 애니메이션 리셋
      t.classList.add('card-target-active');
    });
    setTimeout(function () {
      targets.forEach(function (t) {
        t.classList.remove('card-target-active');
      });
    }, 1800);
  }

  var secs = localRows
    .map(function (a) {
      var id = getTargetId(a);
      return id ? document.getElementById(id) : null;
    })
    .filter(Boolean);

  function spy() {
    if (!scroll || !secs.length || isManualClick) return;

    // 맨 아래 도달 시: 마지막 행의 후보들 확인
    if (scroll.scrollTop + scroll.clientHeight >= scroll.scrollHeight - 10) {
      var lastTop = secs[secs.length - 1].offsetTop;
      var lastRow = secs.filter(function (el) { return Math.abs(el.offsetTop - lastTop) < 30; });
      if (lastRow.some(function (el) { return el.id === currentActiveId; })) {
        return;
      }
      mark(secs[secs.length - 1].id);
      return;
    }

    var line = scroll.scrollTop + scroll.clientHeight / 3;
    var maxTop = -1;
    var candidates = [];
    secs.forEach(function (el) {
      if (el.offsetTop <= line) {
        if (el.offsetTop > maxTop + 30) {
          maxTop = el.offsetTop;
          candidates = [el];
        } else if (Math.abs(el.offsetTop - maxTop) <= 30) {
          candidates.push(el);
        }
      }
    });

    if (!candidates.length) {
      candidates = [secs[0]];
    }

    var alreadyActive = candidates.some(function (el) { return el.id === currentActiveId; });
    if (alreadyActive) {
      return;
    }

    mark(candidates[0].id);
  }

  if (scroll) {
    scroll.addEventListener('scroll', spy, { passive: true });
    // 초기 렌더링 시 최상단(0) 즉시 안착 및 첫 항목 활성화
    scroll.scrollTop = 0;
    if (secs.length) mark(secs[0].id);
  }

  // 사이드바 클릭 이벤트 처리 (즉각 하이라이트 + 카드 발광 + 스무스 이동)
  localRows.forEach(function (a) {
    a.addEventListener('click', function (e) {
      var tid = getTargetId(a);
      var el = tid ? document.getElementById(tid) : null;
      if (!el || !scroll) return;
      e.preventDefault();

      // 1. 클릭된 사이드바 버튼 즉각 활성화 표시
      mark(tid);

      // 2. 타겟 카드 네온 글로우 발광 효과
      highlightCard(el);

      // 3. 스크롤 스파이 덮어쓰기 방지 (1.2초간 수동 클릭 우선)
      isManualClick = true;
      clearTimeout(clickTimer);
      clickTimer = setTimeout(function () {
        isManualClick = false;
      }, 1200);

      // 4. 부드러운 스크롤 이동 (URL 주소창 해시 변경 없음 -> 새로고침/재진입 시 100% 최상단 유지)
      scroll.scrollTo({ top: Math.max(0, el.offsetTop - 14), behavior: 'smooth' });
    });
  });

  // 테마 토글 (다크 기본)
  var root = document.documentElement;
  var btn = document.getElementById('theme-btn');
  try {
    var saved = localStorage.getItem('theme');
    if (saved) root.setAttribute('data-theme', saved);
  } catch (e) {}

  if (btn) {
    btn.addEventListener('click', function () {
      var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('theme', next); } catch (e) {}
      window.dispatchEvent(new Event('resize'));
    });
  }
})();
