// Files slice (F02, F05, F06 create mode, F09, F10, S05). The screens are built in officekit-files.js.
// Keep this register() call first. List destinations one `id: { tab: '…', … },` line
// each: tests/ui-search-routing.test.mjs parses them against the live catalogue.
window.OfficeKitExtensions.register({
  slice: 'files',
  destinations: {
    zip_create: { tab: 'workspace', fileTool: 'archive', sliceView: 'archive-create' },
    zip_extract: { tab: 'workspace', fileTool: 'archive', sliceView: 'archive-extract' },
    archive_inspector: { tab: 'workspace', fileTool: 'archive', sliceView: 'archive-inspect' },
    file_info: { tab: 'workspace', sliceView: 'file_info' },
    file_compare: { tab: 'workspace', sliceView: 'file_compare' },
    file_age_finder: { tab: 'workspace', sliceView: 'file_age_finder' },
    empty_file_finder: { tab: 'workspace', sliceView: 'empty_file_finder' },
    empty_folder_finder: { tab: 'workspace', sliceView: 'empty_folder_finder' },
    symlink_inspector: { tab: 'workspace', sliceView: 'symlink_inspector' },
    trash_restore: { tab: 'workspace', sliceView: 'trash_restore' },
  },
  tabs: [],
  openView(view) {
    // Runs after selectSearchTool switches tab. Before the Files workspace is bound there is nothing to open.
    if (!window.officekitDirectFilesReady) return;
    if (view === 'archive-create' || view === 'archive-extract' || view === 'archive-inspect') {
      const mode = document.getElementById('direct-archive-mode');
      if (!mode) return;
      // Extract and Inspect both open the browse-and-extract mode; Inspect shows the contents first.
      mode.value = view === 'archive-create' ? 'archive-create' : 'archive-extract';
      mode.dispatchEvent(new Event('change'));
      return;
    }
    officekitOpenDirectFileTool(view);
  },
});
