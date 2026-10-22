// Shared by dashboard.html and both report viewers: renders marked output, then strips it down to an allowlist.

function isSafeMarkdownUrl(rawUrl) {
    if (!rawUrl) return true;

    const compactUrl = String(rawUrl)
        .trim()
        .replace(/[\u0000-\u001F\u007F\s]+/g, '');
    if (!compactUrl) return true;

    try {
        const url = new URL(compactUrl, window.location.origin);
        return ['http:', 'https:', 'mailto:', 'tel:'].includes(
            url.protocol
        );
    } catch (error) {
        return false;
    }
}

const SAFE_MARKDOWN_TAGS = new Set(['p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'em', 'strong', 'b', 'i', 'u', 's', 'del', 'ins', 'sub', 'sup', 'a', 'img', 'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'span', 'div', 'kbd', 'mark', 'small', 'details', 'summary', 'input']);

function sanitizeRenderedMarkdown(html) {
    const template = document.createElement('template');
    template.innerHTML = html;

    Array.from(template.content.querySelectorAll('*')).forEach(element => {
        const tag = element.tagName.toLowerCase();
        if (!SAFE_MARKDOWN_TAGS.has(tag)) {
            element.remove();
            return;
        }

        // Only marked's task-list checkboxes survive as inputs.
        if (tag === 'input') {
            if ((element.getAttribute('type') || '').toLowerCase() !== 'checkbox') {
                element.remove();
                return;
            }
            Array.from(element.attributes).forEach(attribute => {
                if (!['type', 'checked', 'disabled'].includes(attribute.name.toLowerCase())) {
                    element.removeAttribute(attribute.name);
                }
            });
            return;
        }

        Array.from(element.attributes).forEach(attribute => {
            const name = attribute.name.toLowerCase();
            if (name.startsWith('on') || name === 'style') {
                element.removeAttribute(attribute.name);
            }
        });
    });

    template.content.querySelectorAll('a[href]').forEach(link => {
        if (!isSafeMarkdownUrl(link.getAttribute('href'))) {
            link.removeAttribute('href');
            link.removeAttribute('target');
            return;
        }

        link.setAttribute('rel', 'noopener noreferrer');
        link.setAttribute('target', '_blank');
    });

    template.content.querySelectorAll('img[src]').forEach(image => {
        if (isSafeMarkdownUrl(image.getAttribute('src'))) return;

        image.replaceWith(
            document.createTextNode(image.getAttribute('alt') || '')
        );
    });

    return template.innerHTML;
}

// CommonMark flanking rules reject `**‘관찰’**로` (punctuation, then 조사), so pair `**…**` within a line directly.
const CJK_STRONG_EXTENSION = {
    name: 'cjkStrong',
    level: 'inline',
    start(src) {
        return src.indexOf('**');
    },
    tokenizer(src) {
        const m = /^\*\*(?![\s*])([^\n]*?[^\s*])\*\*/.exec(src);
        if (!m) return undefined;
        // An odd backtick count means a code span straddles the closing `**`.
        if ((m[1].split('`').length - 1) % 2) return undefined;
        return {
            type: 'strong',
            raw: m[0],
            text: m[1],
            tokens: this.lexer.inlineTokens(m[1])
        };
    }
};

marked.use({ extensions: [CJK_STRONG_EXTENSION] });

function renderSafeMarkdown(markdown) {
    return sanitizeRenderedMarkdown(marked.parse(markdown || ''));
}
