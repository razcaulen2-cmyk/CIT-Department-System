const studentsChart = document.getElementById("studentsChart");

if (studentsChart) {
    const labels = studentsChart.dataset.labels ? JSON.parse(studentsChart.dataset.labels) : ["BSCS", "BSIS", "BLIS"];
    const values = studentsChart.dataset.values ? JSON.parse(studentsChart.dataset.values) : [30, 25, 15];

    new Chart(studentsChart, {
        type: "pie",
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: [
                    "rgba(59, 130, 246, 0.9)",
                    "rgba(236, 72, 153, 0.9)",
                    "rgba(245, 158, 11, 0.9)"
                ],
                borderColor: ["#0b0b0b", "#0b0b0b", "#0b0b0b"],
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { position: "bottom" }
            }
        }
    });
}

const paymentsChart = document.getElementById("paymentsChart");

if (paymentsChart) {
    const labels = paymentsChart.dataset.labels ? JSON.parse(paymentsChart.dataset.labels) : ["1st", "2nd", "Summer"];
    const values = paymentsChart.dataset.values ? JSON.parse(paymentsChart.dataset.values) : [10000, 18000, 4000];

    new Chart(paymentsChart, {
        type: "bar",
        data: {
            labels,
            datasets: [{
                label: "Payments",
                data: values,
                backgroundColor: "rgba(59, 130, 246, 0.85)",
                borderColor: "rgba(37, 99, 235, 0.9)",
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    });
}

let currentStudent = null;
let studentTapModal = null;
let paymentModal = null;
let receiptPreviewModal = null;
let deleteTransactionModal = null;
let pendingReceipt = null;
let refreshAfterPrint = false;
let transactionToDelete = null;
let selectedThermalPrinter = '';

document.addEventListener('DOMContentLoaded', function() {
    const studentTapModalElement = document.getElementById('studentTapModal');
    const paymentModalElement = document.getElementById('paymentModal');
    const receiptPreviewModalElement = document.getElementById('receiptPreviewModal');
    const deleteTransactionModalElement = document.getElementById('deleteTransactionModal');
    const deleteTransactionForm = document.getElementById('deleteTransactionForm');
    const transactionReportForm = document.getElementById('transactionReportForm');
    const transactionReportPreview = document.getElementById('transactionReportPreview');
    const transactionReportError = document.getElementById('transactionReportError');
    const transactionReportLoading = document.getElementById('transactionReportLoading');
    const generateTransactionReportButton = document.getElementById('generateTransactionReportButton');
    const printTransactionReportButton = document.getElementById('printTransactionReportButton');
    const transactionReportModalElement = document.getElementById('generateTransactionReportModal');
    const balanceReportForm = document.getElementById('balanceReportForm');
    const balanceReportPreview = document.getElementById('balanceReportPreview');
    const balanceReportError = document.getElementById('balanceReportError');
    const balanceReportLoading = document.getElementById('balanceReportLoading');
    const generateBalanceReportButton = document.getElementById('generateBalanceReportButton');
    const printBalanceReportButton = document.getElementById('printBalanceReportButton');
    const balanceReportModalElement = document.getElementById('generateBalanceReportModal');
    const receiptPaperWidth = document.getElementById('receiptPaperWidth');
    const tapStudentId = document.getElementById('tapStudentId');
    const thermalPrinterSelect = document.getElementById('thermalPrinterSelect');

    if (studentTapModalElement) {
        studentTapModal = bootstrap.Modal.getOrCreateInstance(studentTapModalElement);
        studentTapModalElement.addEventListener('shown.bs.modal', function() {
            window.requestAnimationFrame(() => {
                tapStudentId?.focus();
                tapStudentId?.setSelectionRange(tapStudentId.value.length, tapStudentId.value.length);
            });
        });
    }
    if (paymentModalElement) {
        paymentModal = bootstrap.Modal.getOrCreateInstance(paymentModalElement);
    }
    if (receiptPreviewModalElement) {
        receiptPreviewModal = bootstrap.Modal.getOrCreateInstance(receiptPreviewModalElement);
        receiptPreviewModalElement.addEventListener('shown.bs.modal', refreshThermalPrinters);
        receiptPreviewModalElement.addEventListener('hidden.bs.modal', function() {
            if (refreshAfterPrint) {
                location.reload();
            }
            pendingReceipt = null;
            refreshAfterPrint = false;
        });
    }
    if (deleteTransactionModalElement) {
        deleteTransactionModal = bootstrap.Modal.getOrCreateInstance(deleteTransactionModalElement);
        deleteTransactionModalElement.addEventListener('hidden.bs.modal', function() {
            document.getElementById('deleteTransactionForm').reset();
            document.getElementById('deleteTransactionError').classList.add('d-none');
            transactionToDelete = null;
        });
    }
    if (deleteTransactionForm) {
        deleteTransactionForm.addEventListener('submit', submitDeleteTransaction);
    }
    if (transactionReportForm && transactionReportPreview && transactionReportError
        && transactionReportLoading && generateTransactionReportButton && printTransactionReportButton) {
        transactionReportForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            transactionReportError.classList.add('d-none');
            transactionReportError.textContent = '';
            transactionReportPreview.replaceChildren();
            printTransactionReportButton.disabled = true;
            generateTransactionReportButton.disabled = true;
            transactionReportLoading.classList.remove('d-none');

            try {
                const query = new URLSearchParams(new FormData(transactionReportForm));
                const response = await fetch(`${transactionReportForm.action}?${query.toString()}`, {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                });
                if (!response.ok || response.redirected) {
                    throw new Error('Unable to generate the report. Please try again.');
                }

                transactionReportPreview.innerHTML = await response.text();
                printTransactionReportButton.disabled = false;
            } catch (error) {
                transactionReportError.textContent = error.message || 'Unable to generate the report. Please try again.';
                transactionReportError.classList.remove('d-none');
            } finally {
                transactionReportLoading.classList.add('d-none');
                generateTransactionReportButton.disabled = false;
            }
        });

        printTransactionReportButton.addEventListener('click', () => {
            if (!transactionReportPreview.childElementCount) return;
            window.print();
        });
    }
    if (transactionReportModalElement) {
        transactionReportModalElement.addEventListener('hidden.bs.modal', () => {
            transactionReportForm?.reset();
            transactionReportPreview?.replaceChildren();
            transactionReportError?.classList.add('d-none');
            if (printTransactionReportButton) printTransactionReportButton.disabled = true;
        });
    }
    if (balanceReportForm && balanceReportPreview && balanceReportError
        && balanceReportLoading && generateBalanceReportButton && printBalanceReportButton) {
        balanceReportForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            balanceReportError.classList.add('d-none');
            balanceReportError.textContent = '';
            balanceReportPreview.replaceChildren();
            printBalanceReportButton.disabled = true;
            generateBalanceReportButton.disabled = true;
            balanceReportLoading.classList.remove('d-none');

            try {
                const query = new URLSearchParams(new FormData(balanceReportForm));
                const response = await fetch(`${balanceReportForm.action}?${query.toString()}`, {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                });
                if (!response.ok || response.redirected) {
                    throw new Error('Unable to generate the report. Please try again.');
                }

                balanceReportPreview.innerHTML = await response.text();
                printBalanceReportButton.disabled = false;
            } catch (error) {
                balanceReportError.textContent = error.message || 'Unable to generate the report. Please try again.';
                balanceReportError.classList.remove('d-none');
            } finally {
                balanceReportLoading.classList.add('d-none');
                generateBalanceReportButton.disabled = false;
            }
        });

        printBalanceReportButton.addEventListener('click', () => {
            if (!balanceReportPreview.childElementCount) return;
            window.print();
        });
    }
    if (balanceReportModalElement) {
        balanceReportModalElement.addEventListener('hidden.bs.modal', () => {
            balanceReportForm?.reset();
            balanceReportPreview?.replaceChildren();
            balanceReportError?.classList.add('d-none');
            if (printBalanceReportButton) printBalanceReportButton.disabled = true;
        });
    }
    if (receiptPaperWidth) {
        receiptPaperWidth.addEventListener('change', applyReceiptPaperWidth);
        applyReceiptPaperWidth();
    }
    if (thermalPrinterSelect) {
        thermalPrinterSelect.addEventListener('change', selectThermalPrinter);
    }

    if (tapStudentId) {
        tapStudentId.addEventListener('keydown', function(event) {
            if (event.key === 'Enter') {
                event.preventDefault();
                const studentId = this.value.trim();
                if (studentId) {
                    fetchAndDisplayBalance(studentId);
                }
            }
        });

    }

    const proceedButton = document.getElementById('proceedAttendanceTransaction');
    if (proceedButton) {
        proceedButton.addEventListener('click', proceedAttendanceTransaction);
    }

    document.querySelectorAll('.delete-transaction-btn').forEach((button) => {
        button.addEventListener('click', () => openDeleteTransactionModal(button));
    });
    document.querySelectorAll('.print-transaction-btn').forEach((button) => {
        button.addEventListener('click', () => printExistingTransaction(button));
    });
});

function openStudentTapModal() {
    const input = document.getElementById('tapStudentId');
    if (!studentTapModal || !input) return;

    input.value = '';
    studentTapModal.show();
}

function openPaymentModal() {
    if (paymentModal) paymentModal.show();
}

function setThermalPrinterStatus(message, isError = false) {
    const status = document.getElementById('thermalPrinterStatus');
    if (!status) return;
    status.textContent = message;
    status.classList.toggle('text-danger', isError);
    status.classList.toggle('text-success', !isError && Boolean(message));
}

async function refreshThermalPrinters() {
    const printerSelect = document.getElementById('thermalPrinterSelect');
    if (!printerSelect) return;
    const previousPrinter = selectedThermalPrinter || printerSelect.value;
    try {
        const response = await fetch('/api/thermal-printers');
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to list Windows printer queues.');

        printerSelect.replaceChildren(new Option('Select PT-210 printer queue', ''));
        data.printers.forEach((name) => printerSelect.add(new Option(name, name)));
        selectedThermalPrinter = data.printers.includes(previousPrinter)
            ? previousPrinter
            : data.printers.find((name) => name.toLowerCase() === 'pos80 printer') || '';
        printerSelect.value = selectedThermalPrinter;

        if (!data.printers.length) {
            setThermalPrinterStatus('Windows sees the USB printer, but no printer queue is installed. Add a queue on USB001 to enable raw ESC/POS printing.', true);
        } else {
            setThermalPrinterStatus(selectedThermalPrinter
                ? `Selected ${selectedThermalPrinter}.`
                : 'Select the PT-210 printer queue. Receipts are sent as raw ESC/POS data through the Windows spooler.');
        }
    } catch (error) {
        selectedThermalPrinter = '';
        printerSelect.replaceChildren(new Option('No Windows printer queues available', ''));
        setThermalPrinterStatus(`Unable to list Windows printer queues: ${error.message}`, true);
    }
}

function selectThermalPrinter() {
    const printerSelect = document.getElementById('thermalPrinterSelect');
    selectedThermalPrinter = printerSelect?.value || '';
    if (!selectedThermalPrinter) {
        setThermalPrinterStatus('No printer selected.');
        return;
    }
    setThermalPrinterStatus(`Selected ${selectedThermalPrinter}.`);
}

function fetchAndDisplayBalance(studentId) {
    fetch(`/api/student-balance/${encodeURIComponent(studentId)}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('Student not found');
            }
            return response.json();
        })
        .then(data => {
            currentStudent = data;
            displayBalance(data);
            studentTapModal.hide();
        })
        .catch(error => {
            alert('Error: ' + error.message);
            if (document.getElementById('studentTapModal')?.classList.contains('show')) {
                document.getElementById('tapStudentId')?.focus();
            }
        });
}

function displayBalance(data) {
    const balanceCard = document.getElementById('balanceCard');
    if (balanceCard) {
        document.getElementById('balanceStudentName').textContent = `${data.firstname} ${data.lastname}`;
        document.getElementById('balanceStudentInfo').textContent = `${data.student_id} • ${data.course} • Year ${data.year_level}`;
        document.getElementById('balanceFunds').textContent = `PHP ${parseFloat(data.total_funds).toFixed(2)}`;
        document.getElementById('balanceFines').textContent = `PHP ${parseFloat(data.total_fines).toFixed(2)}`;
        document.getElementById('balanceTotal').textContent = `PHP ${parseFloat(data.total_balance).toFixed(2)}`;
        balanceCard.style.display = 'block';
    }

    setPaymentStudent(data);
}

function setPaymentStudent(data) {
    document.getElementById('paymentStudentName').textContent = `${data.firstname} ${data.lastname}`;
    document.getElementById('paymentStudentDetails').textContent =
        data.student_id || 'No student ID assigned';
}

async function proceedAttendanceTransaction() {
    const button = document.getElementById('proceedAttendanceTransaction');
    const attendanceModalElement = document.getElementById('studentAttendanceModal');
    const studentId = attendanceModalElement.dataset.paymentStudentId;

    if (!studentId) {
        alert('Unable to identify this student for payment.');
        return;
    }

    button.disabled = true;
    try {
        const response = await fetch(`/api/student-balance/${encodeURIComponent(studentId)}`);
        const data = await response.json();
        if (!response.ok || data.error) {
            throw new Error(data.error || 'Unable to load student balance.');
        }

        currentStudent = data;
        document.getElementById('paymentForm').reset();
        document.getElementById('amount').disabled = false;
        document.getElementById('maxAmount').textContent = '';
        setPaymentStudent(data);

        attendanceModalElement.addEventListener('hidden.bs.modal', function() {
            paymentModal.show();
        }, {once: true});
        bootstrap.Modal.getOrCreateInstance(attendanceModalElement).hide();
    } catch (error) {
        alert('Error: ' + error.message);
    } finally {
        button.disabled = false;
    }
}

function updateAmountField() {
    const paymentType = document.getElementById('paymentType').value;
    const transactionType = document.getElementById('transactionType').value;
    const amountField = document.getElementById('amount');

    if (paymentType === 'Full' && currentStudent && transactionType) {
        const amount = transactionType === 'Funds'
            ? currentStudent.total_funds
            : currentStudent.total_fines;
        amountField.value = amount.toFixed(2);
        amountField.disabled = true;
        document.getElementById('maxAmount').textContent =
            `Full amount for ${transactionType}: PHP ${amount.toFixed(2)}`;
    } else {
        amountField.disabled = false;
        amountField.value = '';
        document.getElementById('maxAmount').textContent = '';
    }
}

async function submitPayment() {
    if (!currentStudent) {
        alert('Please tap a student ID first');
        return;
    }

    const formData = {
        student_id: currentStudent.payment_key || currentStudent.student_id,
        transaction_type: document.getElementById('transactionType').value,
        payment_type: document.getElementById('paymentType').value,
        amount: document.getElementById('amount').value,
        academic_year: document.getElementById('academicYear').value,
        semester: document.getElementById('semester').value
    };

    if (!formData.transaction_type || !formData.payment_type || !formData.amount || !formData.academic_year || !formData.semester) {
        alert('Please fill in all fields');
        return;
    }

    const submitButton = document.querySelector('#paymentModal .modal-footer .btn-dark');
    if (submitButton) submitButton.disabled = true;

    try {
        const response = await fetch('/api/process-payment', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(formData)
        });
        const data = await response.json();
        if (!response.ok || data.error || !data.transaction_no) {
            throw new Error(data.error || 'The payment was not recorded successfully.');
        }

        pendingReceipt = {
            studentName: `${currentStudent.firstname} ${currentStudent.lastname}`,
            paymentType: formData.payment_type === 'Full' ? 'Full Payment' : 'Partial Payment',
            transactionType: formData.transaction_type,
            amount: `PHP ${Number(formData.amount).toFixed(2)}`,
            academicYear: formData.academic_year,
            semester: formData.semester,
            transactionDate: data.transaction_date,
            transactionNo: data.transaction_no
        };
        refreshAfterPrint = true;
        renderTransactionReceipt(pendingReceipt);

        document.getElementById('paymentModal').addEventListener('hidden.bs.modal', function() {
            receiptPreviewModal.show();
        }, {once: true});
        paymentModal.hide();
    } catch (error) {
        alert('Error processing payment: ' + error.message);
    } finally {
        if (submitButton) submitButton.disabled = false;
    }
}

function renderTransactionReceipt(receipt) {
    Object.entries(receipt).forEach(([field, value]) => {
        const target = document.querySelector(`[data-receipt-field="${field}"]`);
        if (target) target.textContent = value;
    });
}

async function printTransactionReceipt() {
    if (!pendingReceipt) {
        alert('There is no completed transaction to print.');
        return;
    }
    if (!selectedThermalPrinter) {
        alert('Select the PT-210 Windows printer queue before printing.');
        return;
    }
    const printButton = document.getElementById('printReceiptButton');
    if (printButton) printButton.disabled = true;
    try {
        const payload = await createThermalReceipt(pendingReceipt);
        let binaryPayload = '';
        const binaryChunkSize = 0x8000;
        for (let offset = 0; offset < payload.length; offset += binaryChunkSize) {
            binaryPayload += String.fromCharCode(...payload.subarray(offset, offset + binaryChunkSize));
        }
        const response = await fetch('/api/thermal-printers/print', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                printer_name: selectedThermalPrinter,
                payload: btoa(binaryPayload)
            })
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Windows could not send the receipt to the printer.');
        }
        setThermalPrinterStatus(`Receipt sent to ${selectedThermalPrinter} (job ${data.job_id}).`);
    } catch (error) {
        setThermalPrinterStatus(`Unable to print receipt: ${error.message}`, true);
        alert(`Unable to print receipt: ${error.message}`);
    } finally {
        if (printButton) printButton.disabled = false;
    }
}

function printExistingTransaction(button) {
    pendingReceipt = {
        studentName: button.dataset.studentName,
        paymentType: button.dataset.paymentType === 'Full' ? 'Full Payment' : 'Partial Payment',
        transactionType: button.dataset.transactionType,
        amount: `PHP ${button.dataset.amount}`,
        academicYear: button.dataset.academicYear,
        semester: button.dataset.semester,
        transactionDate: button.dataset.transactionDate,
        transactionNo: button.dataset.transactionId
    };
    refreshAfterPrint = false;
    renderTransactionReceipt(pendingReceipt);
    applyReceiptPaperWidth();
    receiptPreviewModal.show();
}

function applyReceiptPaperWidth() {
    const width = document.getElementById('receiptPaperWidth')?.value === '80' ? '80' : '58';
    const logoWidth = '30mm';
    const receipt = document.getElementById('receiptPrintArea');
    if (receipt) {
        receipt.style.setProperty('--receipt-paper-width', `${width}mm`);
        receipt.style.setProperty('--receipt-logo-width', logoWidth);
    }
}

function wrapReceiptText(context, value, maxWidth) {
    const words = String(value || '-').split(/\s+/);
    const lines = [];
    let line = '';
    words.forEach((originalWord) => {
        let word = originalWord;
        while (word && context.measureText(word).width > maxWidth) {
            let splitAt = 1;
            while (splitAt < word.length && context.measureText(word.slice(0, splitAt + 1)).width <= maxWidth) {
                splitAt += 1;
            }
            if (line) {
                lines.push(line);
                line = '';
            }
            lines.push(word.slice(0, splitAt));
            word = word.slice(splitAt);
        }
        if (line && context.measureText(`${line} ${word}`).width > maxWidth) {
            lines.push(line);
            line = word;
        } else {
            line = line ? `${line} ${word}` : word;
        }
    });
    if (line) lines.push(line);
    return lines.length ? lines : ['-'];
}

async function createThermalReceipt(receipt) {
    const width = document.getElementById('receiptPaperWidth')?.value === '80' ? 80 : 58;
    const dotsPerMillimeter = 8;
    const horizontalPadding = 5 * dotsPerMillimeter;
    const paperWidth = width * dotsPerMillimeter;
    const contentWidth = paperWidth - horizontalPadding * 2;
    const labelWidth = 20 * dotsPerMillimeter;
    const columnGap = dotsPerMillimeter;
    const valueWidth = contentWidth - labelWidth - columnGap;
    const fontSize = 7 * dotsPerMillimeter * 25.4 / 72;
    const lineHeight = fontSize * 1.25;
    const paragraphMargin = dotsPerMillimeter;
    const topPadding = 4 * dotsPerMillimeter;
    const bottomPadding = 10 * dotsPerMillimeter;
    const encoder = new TextEncoder();
    const printableText = (value) => String(value).normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/[^\x20-\x7e]/g, '?');
    const chunks = [];
    const command = (...bytes) => chunks.push(new Uint8Array(bytes));
    const logo = document.querySelector('#receiptPrintArea .receipt-logo');
    const fields = [
        ['Date:', receipt.transactionDate],
        ['Student Name:', receipt.studentName],
        ['Payment Type:', receipt.paymentType],
        ['Transaction Type:', receipt.transactionType],
        ['Amount:', receipt.amount],
        ['Academic Year:', receipt.academicYear],
        ['Semester:', receipt.semester],
        ['Transaction No:', receipt.transactionNo]
    ];

    const canvas = document.createElement('canvas');
    canvas.width = contentWidth;
    canvas.height = 1;
    let context = canvas.getContext('2d', {willReadFrequently: true});
    if (!context) throw new Error('Unable to prepare the receipt for printing.');

    const labelFont = `bold ${fontSize}px Arial, sans-serif`;
    const valueFont = `${fontSize}px Arial, sans-serif`;
    const wrappedFields = fields.map(([label, value]) => {
        context.font = labelFont;
        const labelLines = wrapReceiptText(context, printableText(label), labelWidth);
        context.font = valueFont;
        const valueLines = wrapReceiptText(context, printableText(value), valueWidth);
        return {labelLines, valueLines, rowCount: Math.max(labelLines.length, valueLines.length)};
    });

    const logoWidth = 30 * dotsPerMillimeter;
    const logoHeight = logo?.complete && logo.naturalWidth
        ? Math.max(1, Math.round(logoWidth * logo.naturalHeight / logo.naturalWidth))
        : 0;
    const logoSpacing = logoHeight ? 2 * dotsPerMillimeter : 0;
    let logoBounds = null;
    const headingFontSize = 10 * dotsPerMillimeter * 25.4 / 72;
    const headingLineHeight = headingFontSize * 1.2;
    const dividerSpacing = 3 * dotsPerMillimeter;
    const footerDividerSpacing = 3 * dotsPerMillimeter;
    const headerHeight = logoHeight + logoSpacing + headingLineHeight + 2 * dotsPerMillimeter + 1 + dividerSpacing;
    const fieldsHeight = wrappedFields.reduce(
        (total, field) => total + field.rowCount * lineHeight + paragraphMargin,
        0
    );
    const receiptHeight = Math.ceil(
        topPadding + headerHeight + fieldsHeight + footerDividerSpacing + 1 + bottomPadding
    );
    canvas.height = receiptHeight;
    context = canvas.getContext('2d', {willReadFrequently: true});
    if (!context) throw new Error('Unable to prepare the receipt for printing.');
    context.fillStyle = '#fff';
    context.fillRect(0, 0, canvas.width, canvas.height);

    let y = topPadding;
    if (logoHeight) {
        const logoLeft = Math.round((contentWidth - logoWidth) / 2);
        context.imageSmoothingEnabled = true;
        context.imageSmoothingQuality = 'high';
        context.drawImage(logo, logoLeft, y, logoWidth, logoHeight);
        logoBounds = {left: logoLeft, top: y, width: logoWidth, height: logoHeight};
        y += logoHeight + logoSpacing;
    }
    context.fillStyle = '#000';
    context.textAlign = 'center';
    context.textBaseline = 'alphabetic';
    context.font = `bold ${headingFontSize}px Arial, sans-serif`;
    context.fillText('SBC-CIT', contentWidth / 2, y + headingFontSize);
    y += headingLineHeight + 2 * dotsPerMillimeter;

    context.beginPath();
    context.setLineDash([2, 2]);
    context.moveTo(0, y);
    context.lineTo(contentWidth, y);
    context.strokeStyle = '#000';
    context.lineWidth = 1;
    context.stroke();
    context.setLineDash([]);
    y += 1 + dividerSpacing;

    wrappedFields.forEach(({labelLines, valueLines, rowCount}) => {
        for (let row = 0; row < rowCount; row += 1) {
            const baseline = y + fontSize + row * lineHeight;
            context.textAlign = 'left';
            context.font = labelFont;
            if (labelLines[row]) context.fillText(labelLines[row], 0, baseline);
            context.textAlign = 'right';
            context.font = valueFont;
            if (valueLines[row]) context.fillText(valueLines[row], contentWidth, baseline);
        }
        y += rowCount * lineHeight + paragraphMargin;
    });

    y += footerDividerSpacing;
    context.beginPath();
    context.setLineDash([2, 2]);
    context.moveTo(0, y);
    context.lineTo(contentWidth, y);
    context.strokeStyle = '#000';
    context.lineWidth = 1;
    context.stroke();
    context.setLineDash([]);

    if (logoBounds) {
        const {left, top, width: logoPixelWidth, height: logoPixelHeight} = logoBounds;
        const logoPixels = context.getImageData(left, top, logoPixelWidth, logoPixelHeight);
        const gray = new Float32Array(logoPixelWidth * logoPixelHeight);
        for (let pixel = 0; pixel < gray.length; pixel += 1) {
            const offset = pixel * 4;
            gray[pixel] = (logoPixels.data[offset] * 299
                + logoPixels.data[offset + 1] * 587
                + logoPixels.data[offset + 2] * 114) / 1000;
        }
        for (let row = 0; row < logoPixelHeight; row += 1) {
            for (let column = 0; column < logoPixelWidth; column += 1) {
                const pixel = row * logoPixelWidth + column;
                const oldValue = gray[pixel];
                const newValue = oldValue < 160 ? 0 : 255;
                const error = oldValue - newValue;
                if (column + 1 < logoPixelWidth) gray[pixel + 1] += error * 7 / 16;
                if (row + 1 < logoPixelHeight) {
                    const nextRow = pixel + logoPixelWidth;
                    if (column > 0) gray[nextRow - 1] += error * 3 / 16;
                    gray[nextRow] += error * 5 / 16;
                    if (column + 1 < logoPixelWidth) gray[nextRow + 1] += error / 16;
                }
                logoPixels.data[pixel * 4] = newValue;
                logoPixels.data[pixel * 4 + 1] = newValue;
                logoPixels.data[pixel * 4 + 2] = newValue;
                logoPixels.data[pixel * 4 + 3] = 255;
            }
        }
        context.putImageData(logoPixels, left, top);
    }

    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    const rowBytes = Math.ceil(canvas.width / 8);
    const bitmap = new Uint8Array(rowBytes * canvas.height);
    for (let y = 0; y < canvas.height; y += 1) {
        for (let x = 0; x < canvas.width; x += 1) {
            const offset = (y * canvas.width + x) * 4;
            const luminance = (pixels[offset] * 299 + pixels[offset + 1] * 587 + pixels[offset + 2] * 114) / 1000;
            if (luminance < 160) bitmap[y * rowBytes + Math.floor(x / 8)] |= 0x80 >> (x % 8);
        }
    }

    command(0x1b, 0x40);
    command(0x1b, 0x61, 1);
    command(0x1d, 0x76, 0x30, 0, rowBytes & 0xff, rowBytes >> 8, canvas.height & 0xff, canvas.height >> 8);
    chunks.push(bitmap);
    command(0x1d, 0x56, 0);

    const totalLength = chunks.reduce((total, chunk) => total + chunk.length, 0);
    const payload = new Uint8Array(totalLength);
    let offset = 0;
    chunks.forEach((chunk) => {
        payload.set(chunk, offset);
        offset += chunk.length;
    });
    return payload;
}

function openDeleteTransactionModal(button) {
    transactionToDelete = button;
    document.getElementById('deleteTransactionDetails').textContent =
        `Delete transaction #${button.dataset.transactionId} for ${button.dataset.studentName} (${button.dataset.transactionType}, PHP ${button.dataset.amount}) and restore its exact previous balance?`;
    document.getElementById('deleteTransactionPassword').value = '';
    document.getElementById('deleteTransactionError').classList.add('d-none');
    deleteTransactionModal.show();
    window.setTimeout(() => document.getElementById('deleteTransactionPassword').focus(), 150);
}

async function submitDeleteTransaction(event) {
    event.preventDefault();
    if (!transactionToDelete) return;

    const button = transactionToDelete;
    const transactionId = button.dataset.transactionId;
    const passwordInput = document.getElementById('deleteTransactionPassword');
    const errorElement = document.getElementById('deleteTransactionError');
    const submitButton = document.getElementById('confirmDeleteTransaction');
    const deleteButton = button;
    errorElement.classList.add('d-none');
    submitButton.disabled = true;

    try {
        const response = await fetch(`/api/transactions/${encodeURIComponent(transactionId)}`, {
            method: 'DELETE',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({password: passwordInput.value})
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Unable to reverse this transaction.');
        }

        const transactionRow = deleteButton.closest('tr');
        if (transactionRow) transactionRow.remove();
        deleteTransactionModal.hide();
        window.setTimeout(() => location.reload(), 150);
    } catch (error) {
        errorElement.textContent = error.message;
        errorElement.classList.remove('d-none');
        passwordInput.value = '';
        passwordInput.focus();
    } finally {
        submitButton.disabled = false;
    }
}