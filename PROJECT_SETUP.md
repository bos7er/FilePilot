# Publish FilePilot on GitHub

These instructions describe the GitHub website's English UI.

## Step 1 — Upload the project

1. Create a **public** repository named `FilePilot`.
2. On **Code**, click **Add file → Upload files**.
3. Unzip this project on your computer and drag in **all files and folders**, not the ZIP itself.
4. Confirm that the path `.github/workflows/build-windows.yml` exists in the repository.
5. Commit your changes to `main`.

## Step 2 — Build the Windows executable

1. Open **Actions → Build FilePilot for Windows**.
2. Open the latest run, or choose **Run workflow**.
3. After a **green check**, open **Artifacts → FilePilot-Windows-EXE**.
4. Extract the archive. It contains `FilePilot.exe`.
5. Test it locally before publishing a public release.

## Step 3 — Publish a downloadable release

1. Open **Releases → Draft a new release**.
2. Create the tag `v1.0.0` targeting `main`.
3. Set the title `FilePilot v1.0.0`.
4. Attach `FilePilot.exe` in the **Assets** area.
5. Publish the release. The website's **Download for Windows** button now links to it.

## Step 4 — Enable the website

1. Open **Settings → Pages**.
2. Under **Build and deployment**, choose **Deploy from a branch**.
3. Select branch `main`, folder `/docs`, then **Save**.
4. Visit `https://bos7er.github.io/FilePilot/` once GitHub Pages is deployed.

## Reminder

If **Actions** is empty, ensure the workflow file is committed at the *exact* location `.github/workflows/build-windows.yml` on the default branch. Windows EXEs cannot be produced merely by renaming a `.py` or `.zip` file.
