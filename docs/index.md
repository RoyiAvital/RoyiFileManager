# RoyiFileManager

A keyboard-focused dual-pane file manager for Windows.

Minimal interface. Fast navigation. Powerful search. Commands are always close.

<figure class="product-shot" markdown>
  ![RoyiFileManager showing C drive and Windows folder](assets/royifilemanager-dual-pane.png)
  <figcaption>Minimalistic, Keyboard Focused Dual Pane UI</figcaption>
</figure>

!!! info
    The development began as a fork of [`fman`](https://github.com/mherrmann/fman) by [Michael Herrmann](https://github.com/mherrmann).

## Features

- **Performance** - Architecture based on snapshot file listing, virtual rows and background projections for **responsiveness** and **reactivity**.
- **Fuzzy Find Files** - Search the path hierarchy with [`fzf`](https://github.com/junegunn/fzf) style search syntax.
- **Search Files** - Search files and content through an easy to use UI panel powered by [`ripgrep`](https://github.com/burntsushi/ripgrep).
- **Find Files** - Find files by name, date, size, type and traversal rules through an easy to use UI panel powered by [`fd`](https://github.com/sharkdp/fd).
- **Pane Filter** - Type directly in a pane to filter names with globs, anchors and negation.
- **QuickView Mode** - Preview the selected files over the other pane with ++ctrl+q++.
- **UI Components** - Build richer plug-ins with reusable dialogs, panels and controls.
- **Favorites** - Organize frequently used locations with ++ctrl+b++.
- **Text Editor and Viewer** - Connect external programs to ++f4++ and ++f3++ with predefined presets for [CudaText](https://github.com/Alexey-T/CudaText), [EmEditor](https://www.emeditor.com), [Notepad++](https://github.com/notepad-plus-plus/notepad-plus-plus) and [Notepad 4](https://github.com/zufuliu/notepad4).
- **File and Folder Comparators** - Configure external comparison tools with predefined presets for [Meld](https://meldmerge.org), [Beyond Compare](https://www.scootersoftware.com), [WinMerge](https://github.com/winmerge/winmerge) and [SmartSynchronize](https://www.syntevo.com/smartsynchronize).
- **Archive Handling** - Utilizing `7Zip` library for a feature reach and safe experience with archives.

[Learn the basics](basics.md) or [explore every feature](features.md).

## Development Guidelines

 - **Integrity**: Data safety above all.
 - **Foresighted**: Simple architecture to avoid edge cases.
 - **Focus**: Minimal UI with keyboard based workflow.
 - **Reactivity**: The UI response to user input.
 - **Reachability**: Accessible tools to reach any file / content with ease and speed.
 - **Modularity**: Easy integration of 3rd party tools for synergy.
