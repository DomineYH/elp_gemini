// PDF.js Viewer Implementation
// Based on Mozilla's PDF.js examples

// Set worker source
pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/js/lib/pdf.worker.min.js';

class PDFViewer {
    constructor(url, containerId) {
        this.url = url;
        this.container = document.getElementById(containerId);
        this.pdfDoc = null;
        this.pageNum = 1;
        this.pageRendering = false;
        this.pageNumPending = null;
        this.scale = 1.5;
        this.canvas = document.createElement('canvas');
        this.ctx = this.canvas.getContext('2d');

        // Add canvas to container
        this.container.appendChild(this.canvas);

        // Add controls container
        this.createControls();

        // Initial load
        this.loadDocument();
    }

    createControls() {
        const controls = document.createElement('div');
        controls.className = 'absolute bottom-4 left-1/2 transform -translate-x-1/2 bg-gray-800 bg-opacity-75 text-white px-4 py-2 rounded-full flex items-center space-x-4 z-10';

        // Prev button
        const prevBtn = document.createElement('button');
        prevBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M12.707 5.293a1 1 0 010 1.414L9.414 10l3.293 3.293a1 1 0 01-1.414 1.414l-4-4a1 1 0 010-1.414l4-4a1 1 0 011.414 0z" clip-rule="evenodd" /></svg>';
        prevBtn.onclick = () => this.onPrevPage();

        // Page info
        this.pageInfo = document.createElement('span');
        this.pageInfo.className = 'text-sm font-medium';
        this.pageInfo.textContent = 'Loading...';

        // Next button
        const nextBtn = document.createElement('button');
        nextBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd" /></svg>';
        nextBtn.onclick = () => this.onNextPage();

        controls.appendChild(prevBtn);
        controls.appendChild(this.pageInfo);
        controls.appendChild(nextBtn);

        this.container.appendChild(controls);
    }

    async loadDocument() {
        try {
            this.pdfDoc = await pdfjsLib.getDocument(this.url).promise;
            this.updatePageInfo();
            this.renderPage(this.pageNum);
        } catch (error) {
            console.error('Error loading PDF:', error);
            this.container.innerHTML = `
                <div class="flex items-center justify-center h-full">
                    <p class="text-red-600">PDF를 불러오는 중 오류가 발생했습니다.</p>
                </div>
            `;
        }
    }

    updatePageInfo() {
        if (this.pdfDoc) {
            this.pageInfo.textContent = `${this.pageNum} / ${this.pdfDoc.numPages}`;
        }
    }

    async renderPage(num) {
        this.pageRendering = true;

        try {
            const page = await this.pdfDoc.getPage(num);

            // Calculate scale to fit width
            const viewport = page.getViewport({ scale: 1.0 });
            const containerWidth = this.container.clientWidth;
            const desiredScale = (containerWidth - 40) / viewport.width; // -40 for padding
            this.scale = Math.min(desiredScale, 2.0); // Max scale 2.0

            const scaledViewport = page.getViewport({ scale: this.scale });

            this.canvas.height = scaledViewport.height;
            this.canvas.width = scaledViewport.width;
            this.canvas.className = 'mx-auto shadow-lg';

            const renderContext = {
                canvasContext: this.ctx,
                viewport: scaledViewport
            };

            await page.render(renderContext).promise;

            this.pageRendering = false;

            if (this.pageNumPending !== null) {
                this.renderPage(this.pageNumPending);
                this.pageNumPending = null;
            }
        } catch (error) {
            console.error('Error rendering page:', error);
            this.pageRendering = false;
        }

        this.updatePageInfo();
    }

    queueRenderPage(num) {
        if (this.pageRendering) {
            this.pageNumPending = num;
        } else {
            this.renderPage(num);
        }
    }

    onPrevPage() {
        if (this.pageNum <= 1) {
            return;
        }
        this.pageNum--;
        this.queueRenderPage(this.pageNum);
    }

    onNextPage() {
        if (this.pageNum >= this.pdfDoc.numPages) {
            return;
        }
        this.pageNum++;
        this.queueRenderPage(this.pageNum);
    }
}
