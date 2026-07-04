using System.Runtime.InteropServices;

namespace BlarAI.Desktop.Services;

/// <summary>
/// Classic Win32 open-file dialog (comdlg32 GetOpenFileNameW). The WinUI
/// surface runs de-elevated (Medium integrity; ADR-019), which fixed drag-drop
/// attach (Explorer -> UI is now a same-integrity drop). This legacy common
/// dialog, however, still does not select OneDrive cloud-only (Files-On-Demand)
/// placeholders even unelevated — that needs the modern IFileOpenDialog / WinRT
/// FileOpenPicker (tracked follow-up). Kept for now because drag-drop and the
/// /load command cover attach.
/// </summary>
public static class FileDialog
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct OpenFileName
    {
        public int lStructSize;
        public IntPtr hwndOwner;
        public IntPtr hInstance;
        [MarshalAs(UnmanagedType.LPWStr)] public string? lpstrFilter;
        [MarshalAs(UnmanagedType.LPWStr)] public string? lpstrCustomFilter;
        public int nMaxCustFilter;
        public int nFilterIndex;
        public IntPtr lpstrFile;     // pre-allocated wide-char buffer
        public int nMaxFile;
        [MarshalAs(UnmanagedType.LPWStr)] public string? lpstrFileTitle;
        public int nMaxFileTitle;
        [MarshalAs(UnmanagedType.LPWStr)] public string? lpstrInitialDir;
        [MarshalAs(UnmanagedType.LPWStr)] public string? lpstrTitle;
        public int Flags;
        public short nFileOffset;
        public short nFileExtension;
        [MarshalAs(UnmanagedType.LPWStr)] public string? lpstrDefExt;
        public IntPtr lCustData;
        public IntPtr lpfnHook;
        [MarshalAs(UnmanagedType.LPWStr)] public string? lpTemplateName;
        public IntPtr pvReserved;
        public int dwReserved;
        public int FlagsEx;
    }

    [DllImport("comdlg32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool GetOpenFileNameW(ref OpenFileName ofn);

    private const int OFN_EXPLORER = 0x00080000;
    private const int OFN_FILEMUSTEXIST = 0x00001000;
    private const int OFN_PATHMUSTEXIST = 0x00000800;
    private const int OFN_HIDEREADONLY = 0x00000004;
    private const int OFN_NOCHANGEDIR = 0x00000008;

    // Null-separated, double-null-terminated filter pairs.
    private const string Filter =
        "Image files\0*.png;*.jpg;*.jpeg;*.jpe;*.jfif;*.gif;*.webp;*.bmp;*.dib;*.tif;*.tiff;*.ico;*.tga;*.heic;*.heif;*.avif\0" +
        "Documents\0*.pdf;*.txt;*.md\0" +
        "Video\0*.mp4;*.mov;*.webm\0" +
        "All files\0*.*\0\0";

    /// <summary>Show the dialog. Returns the chosen path, or null if cancelled.</summary>
    public static string? PickFile(IntPtr ownerHwnd)
    {
        const int bufChars = 2048;
        IntPtr buffer = Marshal.AllocHGlobal(bufChars * sizeof(char));
        try
        {
            // Zero the buffer so the result string terminates cleanly.
            for (int i = 0; i < bufChars; i++)
                Marshal.WriteInt16(buffer, i * sizeof(char), 0);

            var ofn = new OpenFileName
            {
                lStructSize = Marshal.SizeOf<OpenFileName>(),
                hwndOwner = ownerHwnd,
                lpstrFilter = Filter,
                nFilterIndex = 1,
                lpstrFile = buffer,
                nMaxFile = bufChars,
                lpstrTitle = "Attach a file to BlarAI",
                Flags = OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST
                        | OFN_HIDEREADONLY | OFN_NOCHANGEDIR,
            };

            return GetOpenFileNameW(ref ofn)
                ? Marshal.PtrToStringUni(buffer)
                : null;
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }
}
