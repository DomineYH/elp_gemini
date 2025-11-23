/**
 * 평가 기준 목록 페이지 스크립트
 * 활성화/비활성화 토글 및 삭제 처리
 */

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
        '⚠️ 활성화 확정을 진행하시겠습니까?\n\n' +
        '이 작업은 다음을 수행합니다:\n' +
        '1. 기존 Vector Store 삭제\n' +
        '2. 활성화된 평가기준들을 Vector Store에 업로드\n\n' +
        '이 작업은 시간이 걸릴 수 있습니다.'
    );

    if (!confirmed) {
        return;
    }

    // 로딩 표시
    const button = event.target;
    const originalText = button.textContent;
    button.textContent = '처리 중...';
    button.disabled = true;

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
                        '활성화 확정에 실패했습니다.'
                    );
                });
            }
            return response.json();
        })
        .then(data => {
            alert(data.message || '활성화 확정 완료!');
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
