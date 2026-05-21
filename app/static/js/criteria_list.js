document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.alias-cell').forEach((cell) => {
    cell.addEventListener('click', () => startInlineEdit(cell));
  });
  document.querySelectorAll('.active-checkbox').forEach((cb) => {
    cb.addEventListener('change', async () => {
      const sid = cb.value;
      const wasChecked = cb.checked;
      const previous = !wasChecked;
      const row = cb.closest('tr');
      const label = row.querySelector('.status-label');
      const previousLabelText = label ? label.textContent : null;
      const finalLabelText = wasChecked ? '활성' : '비활성';
      const pendingLabelText = wasChecked ? '활성 반영중…' : '비활성 반영중…';
      if (label) label.textContent = pendingLabelText;
      cb.disabled = true;
      try {
        const url = wasChecked
          ? `/api/admin/criteria/${sid}/activate`
          : `/api/admin/criteria/${sid}/deactivate`;
        const r = await fetch(url, { method: 'POST' });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        if (label) label.textContent = finalLabelText;
      } catch (err) {
        cb.checked = previous;
        if (label) label.textContent = previousLabelText;
        alert(`상태 변경 실패: ${err.message}`);
      } finally {
        cb.disabled = false;
      }
    });
  });
  document.querySelectorAll('.delete-btn').forEach((b) => {
    b.addEventListener('click', () => {
      if (confirm(`${b.dataset.title} 평가기준을 삭제하시겠습니까?`)) {
        deleteCriteria(b.dataset.stableId);
      }
    });
  });
  document.querySelectorAll('[data-action="replace"]').forEach((b) => {
    b.addEventListener('click', () => {
      const sid = b.dataset.stableId;
      const title = b.dataset.title;
      if (!confirm(
        `${title} 평가기준을 교체합니다.\n` +
        `동일하거나 대체할 PDF를 선택하세요. 새 stable_id가 발급되고 ` +
        `기존 표시 이름(별칭)은 자동으로 승계됩니다.`
      )) return;
      const picker = document.createElement('input');
      picker.type = 'file';
      picker.accept = 'application/pdf,.pdf';
      picker.addEventListener('change', async () => {
        const f = picker.files && picker.files[0];
        if (!f) return;
        await replaceCriteria(sid, f);
      });
      picker.click();
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

async function deleteCriteria(sid) {
  try {
    const r = await fetch(`/api/admin/criteria/${sid}`, { method: 'DELETE' });
    if (!r.ok) throw new Error(await r.text());
    location.reload();
  } catch (e) {
    alert(`삭제 실패: ${e.message}`);
  }
}

async function replaceCriteria(sid, file) {
  const form = new FormData();
  form.append('file', file);
  try {
    const r = await fetch(`/api/admin/criteria/${sid}/replace`, {
      method: 'POST',
      body: form,
    });
    if (!r.ok) throw new Error(await r.text());
    location.reload();
  } catch (e) {
    alert(`교체 실패: ${e.message}`);
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
