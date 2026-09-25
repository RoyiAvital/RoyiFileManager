Question: Explain types of links in windows NTFS / ReFS files system


Windows NTFS and ReFS file systems support three main types of links: hard links, junction points, and symbolic links. These links let you point to files or folders from multiple locations without duplicating the actual data. [1, 2, 3] 
------------------------------
## 1. Hard Links
A hard link is a direct reference to a file's physical data on the disk. [4, 5] 

* How it works: Multiple file names point to the exact same [Master File Table (MFT)](https://en.wikipedia.org/wiki/NTFS) record and cluster data.
* Scope: Restricted strictly to the same volume/drive.
* Files or Folders: Files only (cannot hard-link directories).
* Behavior: If you edit one hard link, the change updates everywhere instantly. If you delete the original file, the data remains accessible through the remaining hard link until the very last link is deleted.
* Command: mklink /H linkName target [1, 4, 5, 6, 7, 8, 9, 10] 

## 2. Directory Junctions (Junction Points)
A junction is a soft link that redirects one folder path to another folder path locally. [2, 6] 

* How it works: Implemented via [NTFS reparse points](https://en.wikipedia.org/wiki/NTFS_reparse_point), acting as a transparent pointer to a directory.
* Scope: Local computer only (cannot point to network shares), but can cross different local volumes.
* Files or Folders: Directories/Folders only.
* Behavior: If the target folder is moved or deleted, the junction breaks and becomes invalid. Widely used by Windows for backward compatibility and profile folder redirection.
* Command: mklink /J linkName target [2, 4, 6, 10, 11] 

## 3. Symbolic Links (Symlinks)
A symbolic link is a flexible soft link that points to a file or a directory target. [9, 10] 

* How it works: Similar to shortcuts or Unix symlinks, it stores the relative or absolute path of the target object.
* Scope: Local files/folders as well as remote network paths (SMB).
* Files or Folders: Both files and directories.
* Behavior: Transparent to applications. If the target is deleted or moved, the symlink does not update automatically and will point to a non-existent location (breaking the link).
* Command: mklink linkName target (for files) or mklink /D linkName target (for directories) [5, 9, 10, 12, 13] 

------------------------------
## Quick Comparison

| Feature | Hard Link | Junction Point | Symbolic Link |
|---|---|---|---|
| Targets | Files only | Directories only | Files or Directories |
| Volume limit | Same drive only | Local drives only | Local or Remote/Network |
| Survives target deletion? | Yes | No | No |
| OS Support | Windows NT4+ | Windows 2000+ | Windows Vista+ |

If you want to explore further, I can help you with:

* Writing specific scripts (e.g., using PowerShell to manage links)
* Use case scenarios (e.g., moving heavy game folders or saving C-drive space)
* Permissions and security rules surrounding reparse points


[1] [https://learn.microsoft.com](https://learn.microsoft.com/en-us/windows/win32/fileio/hard-links-and-junctions)
[2] [https://en.wikipedia.org](https://en.wikipedia.org/wiki/Symbolic_link)
[3] [https://www.youtube.com](https://www.youtube.com/watch?v=PQbGTP0bR9o&t=118)
[4] [https://www.youtube.com](https://www.youtube.com/watch?v=7Rbw953DXg0&t=21)
[5] [https://www.youtube.com](https://www.youtube.com/watch?v=pUPSxf8hc6k)
[6] [https://www.youtube.com](https://www.youtube.com/watch?v=W8qADBA7154&t=6)
[7] [https://en.wikipedia.org](https://en.wikipedia.org/wiki/NTFS_links)
[8] [https://www.linkedin.com](https://www.linkedin.com/posts/2brightsparks-pte-ltd_ntfs-supports-three-different-mechanisms-activity-7490315977310576640-Kcm1)
[9] [https://superuser.com](https://superuser.com/questions/347930/creating-the-equivalent-of-soft-and-hard-links-in-windows)
[10] [https://wentzwu.com](https://wentzwu.com/2012/12/09/ntfs-hard-link-junction-point-and-symbolic-link-2/)
[11] [https://en.wikipedia.org](https://en.wikipedia.org/wiki/NTFS_reparse_point)
[12] [https://superuser.com](https://superuser.com/questions/67870/what-is-the-difference-between-ntfs-hard-links-and-directory-junctions)
[13] [https://blog.walterlv.com](https://blog.walterlv.com/post/ntfs-link-comparisons-en.html)


Question: Are all 3 of them available for non admin users?

No, not by default. While any user can create two of them, standard Windows security policies restrict the third. [1, 2] 
Here is how the restrictions break down for a non-admin user: [3] 

* 
* Hard Links: ✔️ Yes. Any standard user can create hard links for files they have write/modify permissions for. No administrative elevation is required. [3, 4] 
* Directory Junctions: ✔️ Yes. Standard users can create junctions freely within any folder where they have permission to modify files (like their own C:\Users\Username directories). [3, 5] 
* Symbolic Links (Symlinks): ❌ No (by default). Creating symbolic links requires a special Windows privilege (SeCreateSymbolicLinkPrivilege). By default, Windows only grants this to the Administrators group to prevent malicious software from manipulating system paths (a vulnerability known as symbolic link racing). [1, 6] 
* 

## How non-admins can create Symbolic Links
If you are on a non-admin account but still need to create symbolic links, you can use two workarounds: [7, 8] 

   1. Enable Developer Mode (Windows 10/11): Go to Settings > Update & Security > For Developers (or System > For Developers in Windows 11) and toggle Developer Mode to On. This explicitly lifts the admin requirement for the mklink command. [9, 10, 11] 
   2. Modify Group Policy: An administrator can grant your specific standard user account the permission. They can open gpedit.msc and navigate to Computer Configuration > Windows Settings > Security Settings > Local Policies > User Rights Assignment and add your username to Create symbolic links. [7, 12] 

Would you like instructions on how to automate link creation or check if Developer Mode is active on your machine?

[1] [https://security.stackexchange.com](https://security.stackexchange.com/questions/10194/why-do-you-have-to-be-an-admin-to-create-a-symlink-in-windows)
[2] [https://www.2brightsparks.com](https://www.2brightsparks.com/resources/articles/ntfs-hard-links-junctions-and-symbolic-links.html)
[3] [https://www.youtube.com](https://www.youtube.com/watch?v=pUPSxf8hc6k&t=456)
[4] [https://levelup.gitconnected.com](https://levelup.gitconnected.com/windows-links-demystified-symbolic-links-hard-links-and-junctions-explored-60468e283326)
[5] [https://www.quora.com](https://www.quora.com/In-Windows-why-do-you-need-administrator-privileges-to-create-symlinks-of-directories-but-not-if-youre-creating-directory-junctions)
[6] [https://security.stackexchange.com](https://security.stackexchange.com/questions/10194/why-do-you-have-to-be-an-admin-to-create-a-symlink-in-windows)
[7] [https://stackoverflow.com](https://stackoverflow.com/questions/58038683/allow-mklink-for-a-non-admin-user)
[8] [https://wiki.scanframe.com](https://wiki.scanframe.com/en/Configuration/Windows/mklink-for-users)
[9] [https://github.com](https://github.com/volta-cli/volta/issues/1406)
[10] [https://www.howtogeek.com](https://www.howtogeek.com/16226/complete-guide-to-symbolic-links-symlinks-on-windows-or-linux/)
[11] [https://www.howtogeek.com](https://www.howtogeek.com/16226/complete-guide-to-symbolic-links-symlinks-on-windows-or-linux/)
[12] [https://superuser.com](https://superuser.com/questions/1323598/create-symbolic-link-as-regular-user)


Question: What happens in each case if we delete the link itself? Does it affect the target?

Deleting the link itself never deletes the target's data, but how Windows handles the file pointers varies.
Here is what happens in each case when you delete the link:
## 1. Deleting a Hard Link

* Does it affect the target? No, unless it is the very last link.
* What happens: A file on disk is only truly deleted when the number of hard links pointing to it reaches zero. When you delete a hard link, Windows simply subtracts 1 from the file's reference count. If another hard link (or the original file name) still exists, the file data remains perfectly intact and accessible through those remaining links.

## 2. Deleting a Directory Junction

* Does it affect the target? No, but use caution with older tools.
* What happens: If you delete a junction point using modern Windows tools (like pressing Delete in File Explorer, using rmdir in Command Prompt, or Remove-Item in PowerShell), only the link is destroyed. The original target folder and its contents remain completely untouched.
* Warning: If you use ancient command-line tools or certain outdated third-party file managers and tell them to recursively delete the junction folder, they might mistakenly traverse into the target and delete the actual files inside.

## 3. Deleting a Symbolic Link

* Does it affect the target? No.
* What happens: A symbolic link is just a text pointer pointing to a path. Deleting the symlink (file or directory) merely deletes that pointer. The original file or folder at the target destination remains completely unaffected.

------------------------------
## Summary Table

| Link Type | Deleting the Link... | Does it delete target data? |
|---|---|---|
| Hard Link | Reduces reference count by 1. | No (unless it was the last remaining link to that data). |
| Junction | Deletes the pointer folder. | No (target files and folders remain safe). |
| Symlink | Deletes the pointer file/folder. | No (target files and folders remain safe). |

Would you like to see the safest command-line methods to remove these links without risking accidental target deletion?

Question: What about copying or moving?

Copying or moving links in Windows yields highly dynamic behavior depending on the tool you use (File Explorer vs. Command Line / Backup tools).
------------------------------
## 1. Copying a Link (Ctrl + C ➔ Ctrl + V)
When you copy a link using Windows File Explorer, Windows treats the link as a portal. Instead of copying the pointer, it evaluates the link and duplicates the actual target data. [1, 2] 

* 
* Hard Links: File Explorer copies the file data into a brand new, completely independent file at the destination. The new file has no connection to the original MFT record.
* Directory Junctions & Symlink Folders: File Explorer goes into the target folder, reads all its contents, and duplicates every file and subfolder into a normal, standard folder at the destination. [2] 
* File Symlinks: Evaluates the target and copies its contents into a standard, normal file at the destination.
* 

## 💡 The Exception (Command Line / Backups)
If you want to copy the link itself (preserving the shortcut nature without duplicating gigabytes of data), standard File Explorer cannot do it. You have to use specialized command-line tools like Robocopy: [3, 4] 

* 
* robocopy /sl ➔ Copies file/directory Symlinks as links instead of downloading the target data.
* robocopy /sj ➔ Copies Junction points as links instead of downloading the target data. [1, 3, 5] 
* 

------------------------------
## 2. Moving a Link (Ctrl + X ➔ Ctrl + V)
When you move a link, the outcome depends entirely on whether you are moving it within the same drive (e.g., C: to C:) or across different drives (e.g., C: to D:). [6, 7] 
## Scenario A: Moving within the SAME Drive (Volume)
Windows simply changes the file path entry in the file system table.

* 
* Hard Links: Safely moves. You are just moving one of the references. The file data doesn't move on the platter/SSD.
* Junctions & Symlinks: Safely moves. The link file/folder itself moves to the new path. Because it's an absolute path (or a preserved relative path), it remains fully functional and still points to the original target.
* 

## Scenario B: Moving to a DIFFERENT Drive (Cross-Volume)
Windows cannot just change a file path entry; it has to physically write data to the new disk. Therefore, a cross-volume move is treated as a "Copy to destination, then Delete from source" operation.

* 
* Hard Links: Converted to a regular file. Because hard links cannot cross volumes, Windows copies the target's physical data to the new drive as a normal file, then deletes the source hard link. [7] 
* Directory Junctions & Symlink Folders: Converted to regular folders. Windows will pull all the data from the target location, write it as normal folders/files onto the new drive, and then delete the original link from the source drive. (The original target data remains untouched; only the source link is removed). [2] 
* 

------------------------------
## Summary Cheatsheet (File Explorer Default)

| Link Type | Copying it... | Moving it (Same Drive) | Moving it (Different Drive) |
|---|---|---|---|
| Hard Link | Duplicates file data. | Moves link safely. | Copies data to new drive; deletes source link. |
| Junction | Duplicates folder data. | Moves link safely. | Copies data to new drive; deletes source junction. |
| Symlink | Duplicates file/folder data. | Moves link safely. | Copies data to new drive; deletes source symlink. |

Would you like to see how to use Robocopy switches to safely clone folder structures without accidentally pulling and duplicating linked target files?

[1] [https://superuser.com](https://superuser.com/questions/1647873/robocopy-issues-with-symbolic-links-and-output-log-file)
[2] [https://petri.com](https://petri.com/robocopy-complete-guide/)
[3] [https://superuser.com](https://superuser.com/questions/1642106/how-does-robocopy-handle-file-system-links-symbolic-links-hard-links-and-junct)
[4] [https://www.reddit.com](https://www.reddit.com/r/Windows10/comments/1jb6k7f/whats_the_best_way_to_copy_files_while/)
[5] [https://learn.microsoft.com](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/robocopy)
[6] [https://en.wikipedia.org](https://en.wikipedia.org/wiki/Symbolic_link)
[7] [https://linuxize.com](https://linuxize.com/post/hard-links-vs-symbolic-links/)


Question: What if the links are relative path?

Only Symbolic Links (Symlinks) support relative paths. Hard Links and Junction Points inherently rely on absolute physical addresses or full absolute paths, meaning this scenario applies uniquely to Symlinks.
When you use a relative symlink, the link does not store a path like C:\Data\Target.txt. Instead, it stores a path like ..\Target.txt (meaning "look in the parent directory").
Because the path is relative, copying or moving the link completely changes how Windows tries to resolve it.
------------------------------
## 1. Moving a Relative Symlink
When you move a relative symlink, the link will break unless the relative distance to the target remains exactly the same.

* Moving within the Same Drive: Windows moves the link file itself, but it does not update the relative path text stored inside it. If you move a symlink from C:\FolderA to C:\FolderB, it will still look for ..\Target.txt. Since it is now in a new location, it will look in the parent of FolderB. If the target isn't there, the link breaks.
* Moving to a Different Drive: Remember that File Explorer treats a cross-volume move as a "Copy + Delete". File Explorer will resolve the relative path, grab the actual target data, write it as a normal file/folder on the new drive, and delete the relative link from the source.

## 2. Copying a Relative Symlink
The outcome depends heavily on how you copy it.

* Using File Explorer (Ctrl+C / Ctrl+V): File Explorer always resolves the link. It follows the relative path, copies the actual target data, and pastes it as a regular, independent file/folder at the destination. The relative link is completely gone in the copy.
* Using Command Line (robocopy /sl or xcopy /b): This explicitly copies the link itself rather than the target data. The new copy will contain the exact same relative text (e.g., ..\Target.txt).
* If you paste this link into a folder that has the exact same structural relationship to the target, it will work.
   * If you paste it anywhere else, the relative link will instantly break because it is looking for a target that isn't there.

------------------------------
## Visual Example
Imagine this folder structure:

C:\
└── Project\
    ├── Target.txt
    └── Shortcuts\
        └── Link.lnk (Relative Symlink pointing to "..\Target.txt")


* If you move Link.lnk to C:\Project\Backup\Shortcuts\: It breaks. It looks for ..\Target.txt from its new position, which points to C:\Project\Backup\Target.txt (which doesn't exist).
* If you move Link.lnk to D:\Shortcuts\: File Explorer resolves it, copies the actual contents of Target.txt over to D:\Shortcuts\ as a standard file, and deletes the relative link from C:.

Would you like to see the exact command-line syntax for creating relative symlinks so Windows handles them correctly from the start?

