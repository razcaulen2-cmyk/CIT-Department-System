import ctypes
from ctypes import wintypes


PRINTER_ENUM_LOCAL = 0x00000002
ERROR_INSUFFICIENT_BUFFER = 122


class PrinterInfo4W(ctypes.Structure):
    _fields_ = [
        ("pPrinterName", wintypes.LPWSTR),
        ("pServerName", wintypes.LPWSTR),
        ("Attributes", wintypes.DWORD),
    ]


class DocInfo1W(ctypes.Structure):
    _fields_ = [
        ("pDocName", wintypes.LPWSTR),
        ("pOutputFile", wintypes.LPWSTR),
        ("pDatatype", wintypes.LPWSTR),
    ]


def _get_spooler():
    try:
        load_library = ctypes.WinDLL
    except AttributeError as error:
        raise OSError("Windows printer spooler access is only available on Windows.") from error
    return load_library("winspool.drv", use_last_error=True)


def list_local_printers():
    spooler = _get_spooler()
    spooler.EnumPrintersW.argtypes = [
        wintypes.DWORD,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.LPBYTE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    spooler.EnumPrintersW.restype = wintypes.BOOL

    needed = wintypes.DWORD()
    returned = wintypes.DWORD()
    succeeded = spooler.EnumPrintersW(
        PRINTER_ENUM_LOCAL, None, 4, None, 0, ctypes.byref(needed), ctypes.byref(returned)
    )
    if succeeded:
        return []
    if ctypes.get_last_error() != ERROR_INSUFFICIENT_BUFFER:
        raise ctypes.WinError(ctypes.get_last_error())
    if not needed.value:
        return []

    buffer = ctypes.create_string_buffer(needed.value)
    if not spooler.EnumPrintersW(
        PRINTER_ENUM_LOCAL,
        None,
        4,
        ctypes.cast(buffer, wintypes.LPBYTE),
        needed.value,
        ctypes.byref(needed),
        ctypes.byref(returned),
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    printer_info = ctypes.cast(buffer, ctypes.POINTER(PrinterInfo4W))
    return sorted(printer_info[index].pPrinterName for index in range(returned.value))


def print_raw_receipt(printer_name, payload):
    spooler = _get_spooler()
    spooler.OpenPrinterW.argtypes = [
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.c_void_p,
    ]
    spooler.OpenPrinterW.restype = wintypes.BOOL
    spooler.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p]
    spooler.StartDocPrinterW.restype = wintypes.DWORD
    spooler.StartPagePrinter.argtypes = [wintypes.HANDLE]
    spooler.StartPagePrinter.restype = wintypes.BOOL
    spooler.WritePrinter.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    spooler.WritePrinter.restype = wintypes.BOOL
    spooler.EndPagePrinter.argtypes = [wintypes.HANDLE]
    spooler.EndPagePrinter.restype = wintypes.BOOL
    spooler.EndDocPrinter.argtypes = [wintypes.HANDLE]
    spooler.EndDocPrinter.restype = wintypes.BOOL
    spooler.ClosePrinter.argtypes = [wintypes.HANDLE]
    spooler.ClosePrinter.restype = wintypes.BOOL

    printer_handle = wintypes.HANDLE()
    if not spooler.OpenPrinterW(printer_name, ctypes.byref(printer_handle), None):
        raise ctypes.WinError(ctypes.get_last_error())

    document_started = False
    page_started = False
    try:
        document = DocInfo1W("Department Fines Tracker receipt", None, "RAW")
        job_id = spooler.StartDocPrinterW(
            printer_handle, 1, ctypes.cast(ctypes.byref(document), ctypes.c_void_p)
        )
        if not job_id:
            raise ctypes.WinError(ctypes.get_last_error())
        document_started = True

        if not spooler.StartPagePrinter(printer_handle):
            raise ctypes.WinError(ctypes.get_last_error())
        page_started = True

        written = wintypes.DWORD()
        payload_buffer = ctypes.create_string_buffer(payload)
        if not spooler.WritePrinter(
            printer_handle,
            payload_buffer,
            len(payload),
            ctypes.byref(written),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if written.value != len(payload):
            raise OSError(f"Printer accepted {written.value} of {len(payload)} receipt bytes.")

        if not spooler.EndPagePrinter(printer_handle):
            raise ctypes.WinError(ctypes.get_last_error())
        page_started = False
        if not spooler.EndDocPrinter(printer_handle):
            raise ctypes.WinError(ctypes.get_last_error())
        document_started = False
        return job_id
    finally:
        if page_started:
            spooler.EndPagePrinter(printer_handle)
        if document_started:
            spooler.EndDocPrinter(printer_handle)
        if not spooler.ClosePrinter(printer_handle):
            raise ctypes.WinError(ctypes.get_last_error())
