/**
 * 평가 기준 상세 페이지 스크립트
 * 활성화/비활성화 처리
 */

// 전역 변수 (템플릿에서 주입)
let criteriaId;
let criteriaTitle;

/**
 * 페이지 로드 시 초기화
 */
function initCriteriaDetail(id, title) {
    criteriaId = id;
    criteriaTitle = title;
}

/**
 * 평가 기준 활성화
 */
function activateCriteria() {
    const confirmed = confirm(
        `"${criteriaTitle}" 기준을 활성화하시겠습니까?\n\n` +
        '기존 활성 기준은 자동으로 비활성화됩니다.'
    );

    if (!confirmed) return;

    fetch(`/admin/criteria/${criteriaId}/activate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
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
            alert(`"${data.title}" 기준이 활성화되었습니다.`);
            window.location.reload();
        })
        .catch(error => alert(`오류: ${error.message}`));
}

/**
 * 평가 기준 비활성화
 */
function deactivateCriteria() {
    const confirmed = confirm(
        `"${criteriaTitle}" 기준을 비활성화하시겠습니까?`
    );

    if (!confirmed) return;

    fetch('/admin/criteria/deactivate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
    })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(
                        data.detail ||
                        '비활성화에 실패했습니다.'
                    );
                });
            }
            return response.json();
        })
        .then(() => {
            alert('기준이 비활성화되었습니다.');
            window.location.reload();
        })
        .catch(error => alert(`오류: ${error.message}`));
}
