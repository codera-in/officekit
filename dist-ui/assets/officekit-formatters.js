/* Shared display formatting for tool summaries and file/result rows. */
(() => {
  'use strict';

  function fileSize(bytes) {
    if (!Number.isSafeInteger(bytes) || bytes < 0) return 'Size unavailable';
    if (bytes < 1024) return `${bytes.toLocaleString()} ${bytes === 1 ? 'byte' : 'bytes'}`;
    if (bytes < 1024 * 1024) {
      const kibibytes = (bytes / 1024).toFixed(1);
      if (Number(kibibytes) < 1024) return `${kibibytes} KiB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(2)} MiB`;
  }

  window.OfficeKitFormatters = Object.freeze({ fileSize });
})();
