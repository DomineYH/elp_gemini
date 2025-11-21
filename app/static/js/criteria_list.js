/**
 * 평가 기준 목록 페이지 스크립트
 * 활성화 및 삭제 처리
 */

/**
 * 평가 기준 활성화
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

    // 활성화 요청
    fetch(`/admin/criteria/${criteriaId}/activate`, {
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
            alert(
                `"${data.title}" 기준이 활성화되었습니다.`
            );
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
        `⚠️ 경고: "${title}" 기준을 삭제하시겠습니까?\n\n` +
        '이 작업은 다음을 수행합니다:\n' +
        '1. Vector DB에서 임베딩 데이터 삭제\n' +
        '2. 데이터베이스에서 메타데이터 삭제\n' +
        '3. 파일 시스템에서 파일 삭제\n\n' +
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

    // 삭제 요청
    fetch(`/admin/criteria/${criteriaId}`, {
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
            alert(data.message || `"${title}" 기준이 삭제되었습니다.`);
            // 페이지 새로고침
            window.location.reload();
        })
        .catch(error => {
            alert(`삭제 오류: ${error.message}`);
            button.textContent = originalText;
            button.disabled = false;
        });
}
