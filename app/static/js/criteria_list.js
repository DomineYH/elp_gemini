document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.alias-cell').forEach((cell) => {
    cell.addEventListener('click', () => startInlineEdit(cell));
  });
  document.querySelectorAll('.active-radio').forEach((r) => {
    r.addEventListener('change', (e) => {
      const sid = e.target.value;
      activate(sid);
    });
  });
  document.querySelectorAll('[data-action="deactivate"]').forEach((b) => {
    b.addEventListener('click', () => {
      deactivate(b.dataset.stableId);
    });
  });
  document.querySelectorAll('.delete-btn').forEach((b) => {
    b.addEventListener('click', () => {
      if (confirm(`${b.dataset.title} 평가기준을 삭제하시겠습니까?`)) {
        deleteCriteria(b.dataset.stableId);
      }
    });
  });
  const reconcileBtn = document.querySelector('[data-action="reconcile"]');
  if (reconcileBtn) {
    reconcileBtn.addEventListener('click', reconcile);
  }
});

async function startInlineEdit(cell) {
  const row = cell.closest('tr');
  const sid = row.dataset.stableId;
  const original = cell.dataset.original;
  const input = document.createElement('input');
  input.type = 'text';
  input.maxLength = 255;
  input.value = original;
  input.className = 'border rounded px-1 py-0.5 w-full';
  input.dataset.cancelled = 'false';
  cell.replaceWith(input);
  input.focus();

  const reset = (cls, value) => {
    input.dataset.cancelled = 'true';
    const span = document.createElement('span');
    span.className = cls;
    span.dataset.original = value;
    span.textContent = value || '(미설정)';
    input.replaceWith(span);
    span.addEventListener('click', () => startInlineEdit(span));
  };

  const cssClass = cell.className;

  const commit = async () => {
    if (input.dataset.cancelled === 'true') return;
    const next = input.value.trim() || null;
    if (next === original || (next === null && !original)) {
      reset(cssClass, original);
      return;
    }
    try {
      const r = await fetch(`/api/admin/criteria/${sid}/alias`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alias: next }),
      });
      if (!r.ok) throw new Error(await r.text());
      reset(cssClass, next || '');
    } catch (e) {
      alert(`표시 이름 저장 실패: ${e.message}`);
      reset(cssClass, original);
    }
  };

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { commit(); }
    if (e.key === 'Escape') { reset(cssClass, original); }
  });
  input.addEventListener('blur', commit);
}

async function activate(sid) {
  try {
    const r = await fetch(`/api/admin/criteria/${sid}/activate`, { method: 'POST' });
    if (!r.ok) throw new Error(await r.text());
    location.reload();
  } catch (e) {
    alert(`활성화 실패: ${e.message}`);
  }
}

async function deactivate(sid) {
  try {
    const r = await fetch(`/api/admin/criteria/${sid}/deactivate`, { method: 'POST' });
    if (!r.ok) throw new Error(await r.text());
    location.reload();
  } catch (e) {
    alert(`비활성화 실패: ${e.message}`);
  }
}

async function deleteCriteria(sid) {
  try {
    const r = await fetch(`/api/admin/criteria/${sid}`, { method: 'DELETE' });
    if (!r.ok) throw new Error(await r.text());
    location.reload();
  } catch (e) {
    alert(`삭제 실패: ${e.message}`);
  }
}

async function reconcile() {
  try {
    const r = await fetch('/api/admin/criteria/reconcile', { method: 'POST' });
    if (!r.ok) throw new Error(await r.text());
    location.reload();
  } catch (e) {
    alert(`재동기화 실패: ${e.message}`);
  }
}
