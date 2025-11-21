/**
 * 평가 기준 업로드 페이지 스크립트
 * Drag & Drop 업로드 처리
 */

const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const uploadForm = document.getElementById('uploadForm');
const loadingOverlay = document.getElementById('loadingOverlay');
const fileNameDisplay = document.getElementById('fileName');
const submitBtn = document.getElementById('submitBtn');

// Drag & Drop 이벤트 방지
['dragenter', 'dragover', 'dragleave', 'drop']
    .forEach(eventName => {
        dropZone.addEventListener(
            eventName,
            preventDefaults,
            false
        );
    });

function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

// Drag & Drop 하이라이트
['dragenter', 'dragover'].forEach(eventName => {
    dropZone.addEventListener(eventName, highlight, false);
});

['dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, unhighlight, false);
});

function highlight(e) {
    dropZone.classList.add('border-blue-500', 'bg-blue-50');
}

function unhighlight(e) {
    dropZone.classList.remove('border-blue-500', 'bg-blue-50');
}

// 파일 선택 처리
fileInput.addEventListener('change', handleFiles);
dropZone.addEventListener('drop', handleDrop, false);

function handleDrop(e) {
    const dt = e.dataTransfer;
    const files = dt.files;
    fileInput.files = files;
    handleFiles();
}

function handleFiles() {
    const files = fileInput.files;
    if (files.length > 0) {
        const file = files[0];

        // PDF 검증
        if (file.type !== 'application/pdf') {
            alert('PDF 파일만 업로드 가능합니다.');
            fileInput.value = '';
            return;
        }

        // 파일 크기 검증 (10MB)
        const maxSize = 10 * 1024 * 1024;
        if (file.size > maxSize) {
            alert(
                '파일 크기가 10MB를 초과합니다. ' +
                '더 작은 파일을 선택해주세요.'
            );
            fileInput.value = '';
            return;
        }

        const sizeMB = (file.size / 1024 / 1024).toFixed(2);
        fileNameDisplay.textContent =
            `선택된 파일: ${file.name} (${sizeMB}MB)`;
        fileNameDisplay.classList.remove('hidden');
    }
}

// 폼 제출 처리
uploadForm.addEventListener('submit', function(e) {
    e.preventDefault();

    // 제목 검증
    const title = document.getElementById('title').value.trim();
    if (!title) {
        alert('제목을 입력해주세요.');
        return;
    }

    // 파일 검증
    if (!fileInput.files || fileInput.files.length === 0) {
        alert('파일을 선택해주세요.');
        return;
    }

    // 로딩 표시
    loadingOverlay.classList.remove('hidden');
    submitBtn.disabled = true;

    // 폼 제출
    uploadForm.submit();
});
