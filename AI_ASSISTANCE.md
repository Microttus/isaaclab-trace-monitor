# AI assistance disclosure

The initial implementation of IsaacLab Trace Monitor was created with
substantial assistance from OpenAI's ChatGPT.

ChatGPT was used to help:

- design the bounded trace format and application architecture;
- generate and revise portions of the Python/PySide6 application;
- implement the local and SSH/`rsync` source handling;
- create the Isaac Lab/Stable-Baselines3 logging callback;
- draft tests, build scripts, packaging metadata, and documentation;
- diagnose macOS/PyInstaller packaging failures;
- prepare Linux runtime, CI, desktop integration, and packaging support; and
- produce and integrate the application icon.

Martin Økter supplied the application requirements, domain context, and
macOS/Coder usage feedback, and performed practical acceptance testing of the
live and offline monitoring workflows.

The application does not use an OpenAI API at runtime. It does not send trace
files, SSH information, paths, or any other data to OpenAI. ChatGPT was a
development tool, not an application dependency.

The maintainer remains responsible for reviewing, testing, licensing, and
publishing the repository. Future contributions that make substantial use of
generative AI should disclose that use in the pull request or commit message.
