# Notice

The playbooks in this directory are adapted from the poteto-mode playbooks and principle skills of [pstack](https://github.com/cursor/plugins/tree/main/pstack) (cursor/plugins revision `005d8f6`, plugin version 0.15.48). They were rewritten to be harness-neutral and to fit this routing policy: delegation steps became worker steps (AUTH-3), and parallel candidate runs and subagent fan-out were dropped (ORDER-9). Several sentences remain close to the original wording. Each file names its source playbook in `adapted_from`. This project does not install or invoke pstack.

pstack is licensed as follows:

```
MIT License

Copyright (c) 2026 Lauren Tan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN ANY ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
