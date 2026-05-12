/**
 * 평가 기준 목록 페이지 스크립트
 * 활성화/비활성화 토글 및 삭제 처리
 */

/**
 * 동기화 진행 모달 표시
 */
function showSyncProgressModal() {
    const modal = document.createElement('div');
    modal.id = 'sync-progress-modal';
    modal.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
    modal.innerHTML = `
        <div class="bg-white rounded-lg p-8 max-w-sm w-full mx-4 text-center shadow-xl">
            <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
            <h3 class="text-lg font-medium text-gray-900 mb-2">Vector Store 동기화 중...</h3>
            <p class="text-sm text-gray-500">잠시만 기다려주세요.</p>
        </div>
    `;
    document.body.appendChild(modal);
}

/**
 * 동기화 진행 모달 숨기기
 */
function hideSyncProgressModal() {
    const modal = document.getElementById('sync-progress-modal');
    if (modal) {
        modal.remove();
    }
}

/**
 * 동기화 성공 모달 표시
 * @param {number} count - 동기화된 문서 수
 */
function showSyncSuccessModal(count) {
    const modal = document.createElement('div');
    modal.id = 'sync-success-modal';
    modal.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
    modal.innerHTML = `
        <div class="bg-white rounded-lg p-8 max-w-sm w-full mx-4 text-center shadow-xl">
            <div class="h-12 w-12 rounded-full bg-green-100 flex items-center justify-center mx-auto mb-4">
                <svg class="h-6 w-6 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                </svg>
            </div>
            <h3 class="text-lg font-medium text-gray-900 mb-2">동기화 완료!</h3>
            <p class="text-sm text-gray-600 mb-4">${count}개의 평가기준이 Vector Store에 반영되었습니다.</p>
            <button onclick="window.location.reload()" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
                확인
            </button>
        </div>
    `;
    document.body.appendChild(modal);
}

/**
 * 동기화 실패 모달 표시
 * @param {string} message - 오류 메시지
 */
function showSyncErrorModal(message) {
    const modal = document.createElement('div');
    modal.id = 'sync-error-modal';
    modal.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
    modal.innerHTML = `
        <div class="bg-white rounded-lg p-8 max-w-sm w-full mx-4 text-center shadow-xl">
            <div class="h-12 w-12 rounded-full bg-red-100 flex items-center justify-center mx-auto mb-4">
                <svg class="h-6 w-6 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
            </div>
            <h3 class="text-lg font-medium text-gray-900 mb-2">동기화 실패</h3>
            <p class="text-sm text-gray-600 mb-4">${message}</p>
            <button onclick="document.getElementById('sync-error-modal').remove()" class="px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700 transition-colors">
                닫기
            </button>
        </div>
    `;
    document.body.appendChild(modal);
}

/**
 * 평가 기준 활성/비활성 토글
 * @param {number} criteriaId - 기준 문서 ID
 * @param {string} title - 문서 제목
 * @param {string} currentStatus - 현재 상태 ('active' 또는 'uploaded')
 */
function toggleCriteriaStatus(criteriaId, title, currentStatus) {
    const isActive = currentStatus === 'active';
    const action = isActive ? '비활성화' : '활성화';
    const endpoint = isActive ? 'deactivate' : 'activate';

    // 확인 다이얼로그
    const message = isActive
        ? `"${title}" 기준을 비활성화하시겠습니까?`
        : `"${title}" 기준을 활성화하시겠습니까?\n\n기존 활성 기준은 자동으로 비활성화됩니다.`;

    const confirmed = confirm(message);

    if (!confirmed) {
        return;
    }

    // 로딩 표시
    const button = event.target.closest('button');
    const originalHTML = button.innerHTML;
    button.disabled = true;
    button.classList.add('opacity-50', 'cursor-not-allowed');

    // 토글 요청
    fetch(`/api/admin/criteria/${criteriaId}/${endpoint}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
    })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(
                        data.detail ||
                        `${action}에 실패했습니다.`
                    );
                });
            }
            return response.json();
        })
        .then(data => {
            // 성공 메시지 (옵션)
            // alert(data.message || `${action}되었습니다.`);

            // 페이지 새로고침
            window.location.reload();
        })
        .catch(error => {
            alert(`오류: ${error.message}`);
            button.innerHTML = originalHTML;
            button.disabled = false;
            button.classList.remove('opacity-50', 'cursor-not-allowed');
        });
}

/**
 * 평가 기준 활성화 (기존 함수 - 하위 호환성 유지)
 * @param {number} criteriaId - 기준 문서 ID
 * @param {string} title - 문서 제목
 */
function activateCriteria(criteriaId, title) {
    // 확인 다이얼로그
    const confirmed = confirm(
        `"${title}" 기준을 활성화하시겠습니까?\n\n` +
        '기존 활성 기준은 자동으로 비활성화됩니다.'
    );

    if (!confirmed) {
        return;
    }

    // 로딩 표시
    const button = event.target;
    const originalText = button.textContent;
    button.textContent = '처리 중...';
    button.disabled = true;

    // 활성화 요청 (API 경로 사용)
    fetch(`/api/admin/criteria/${criteriaId}/activate`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
    })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(
                        data.detail ||
                        '활성화에 실패했습니다.'
                    );
                });
            }
            return response.json();
        })
        .then(data => {
            alert(data.message || '활성화되었습니다.');
            // 페이지 새로고침
            window.location.reload();
        })
        .catch(error => {
            alert(`오류: ${error.message}`);
            button.textContent = originalText;
            button.disabled = false;
        });
}

/**
 * 활성화 확정
 * active 상태 평가기준들을 Vector Store에 업로드
 */
function confirmActivation() {
    // 확인 다이얼로그
    const confirmed = confirm(
        '⚠️ 동기화 확정을 진행하시겠습니까?\n\n' +
        '이 작업은 다음을 수행합니다:\n' +
        '1. 기존 Vector Store 삭제\n' +
        '2. 새 Vector Store 생성\n' +
        '3. 활성화된 평가기준들만 업로드\n\n' +
        '이 작업은 시간이 걸릴 수 있습니다.'
    );

    if (!confirmed) {
        return;
    }

    // 진행 모달 표시
    showSyncProgressModal();

    // 활성화 확정 요청
    fetch('/api/admin/criteria/confirm-activation', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
    })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(
                        data.detail ||
                        '동기화 확정에 실패했습니다.'
                    );
                });
            }
            return response.json();
        })
        .then(data => {
            hideSyncProgressModal();
            showSyncSuccessModal(data.count || 0);
        })
        .catch(error => {
            hideSyncProgressModal();
            showSyncErrorModal(error.message);
        });
}

/**
 * 평가 기준 삭제
 * @param {number} criteriaId - 기준 문서 ID
 * @param {string} title - 문서 제목
 */
function deleteCriteria(criteriaId, title) {
    // 확인 다이얼로그
    const confirmed = confirm(
        `⚠️ 경고: \"${title}\" 기준을 삭제하시겠습니까?\n\n` +
        '이 작업은 다음을 수행합니다:\n' +
        '1. 데이터베이스에서 메타데이터 삭제\n' +
        '2. 로컬 파일 삭제\n\n' +
        '이 작업은 되돌릴 수 없습니다.'
    );

    if (!confirmed) {
        return;
    }

    // 로딩 표시
    const button = event.target;
    const originalText = button.textContent;
    button.textContent = '삭제 중...';
    button.disabled = true;

    // 삭제 요청 (API 경로 사용)
    fetch(`/api/admin/criteria/${criteriaId}`, {
        method: 'DELETE',
        headers: {
            'Content-Type': 'application/json',
        },
    })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(
                        data.detail ||
                        '삭제에 실패했습니다.'
                    );
                });
            }
            return response.json();
        })
        .then(data => {
            alert(data.message || `\"${title}\" 기준이 삭제되었습니다.`);
            // 페이지 새로고침
            window.location.reload();
        })
        .catch(error => {
            alert(`삭제 오류: ${error.message}`);
            button.textContent = originalText;
            button.disabled = false;
        });
}

// 평가기준 alias 인라인 편집

function isPrintableAscii(s) {
    // 0x20 - 0x7E 범위만 허용 (server-side와 일치)
    return /^[\x20-\x7E]*$/.test(s);
}

async function updateDisplayAlias(criteriaId, newAlias) {
    const payload = newAlias && newAlias.length > 0
        ? { display_alias: newAlias }
        : { display_alias: null };
    const res = await fetch(
        `/api/admin/criteria/${criteriaId}/display-alias`,
        {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }
    );
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return await res.json();
}

function bindAliasCell(span) {
    span.addEventListener('click', () => activateAliasEdit(span));
}

function activateAliasEdit(span) {
    const original = span.dataset.original || '';
    const input = document.createElement('input');
    input.type = 'text';
    input.value = original;
    input.maxLength = 255;
    input.className = 'border rounded px-2 py-1 text-sm w-full';

    let finalized = false;

    const restore = (text) => {
        const newSpan = document.createElement('span');
        newSpan.className = 'alias-cell cursor-pointer hover:bg-blue-50 px-2 py-1 rounded';
        newSpan.dataset.criteriaId = span.dataset.criteriaId;
        newSpan.dataset.original = text;
        newSpan.textContent = text || '(미설정)';
        bindAliasCell(newSpan);
        input.replaceWith(newSpan);
    };

    const commit = async () => {
        if (finalized) return;
        finalized = true;
        const v = input.value.trim();
        if (v && !isPrintableAscii(v)) {
            alert('표시 가능한 ASCII 문자만 허용됩니다.');
            restore(original);
            return;
        }
        try {
            const result = await updateDisplayAlias(span.dataset.criteriaId, v);
            restore(result.display_alias || '');
        } catch (e) {
            alert('업데이트 실패: ' + e.message);
            restore(original);
        }
    };

    const cancel = () => {
        if (finalized) return;
        finalized = true;
        restore(original);
    };

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            commit();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            cancel();
        }
    });
    input.addEventListener('blur', commit);

    span.replaceWith(input);
    input.focus();
    input.select();
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.alias-cell').forEach(bindAliasCell);
});
