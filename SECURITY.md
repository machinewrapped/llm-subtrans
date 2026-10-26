# Security Policy

## Supported Versions

Security fixes are made against the latest release only, which covers the `llm-subtrans` application and the `PySubtrans` package on PyPI.
Please check that an issue can be reproduced with the latest release before reporting it.

## Reporting a Vulnerability

Please do not report security vulnerabilities through public GitHub issues, discussions or pull requests.

Report them privately through GitHub's private vulnerability reporting instead:

1. Go to the [Security tab](https://github.com/machinewrapped/llm-subtrans/security) of the repository.
2. Click **Report a vulnerability**.
3. Describe the issue, the affected version and the steps to reproduce it, with a proof of concept if you have one.

You should receive a response within 14 days.
If the issue is confirmed, a fix will be prepared privately and released before the details are made public.
Reporters are credited in the release notes unless they prefer not to be.

## Scope

Examples of issues that are in scope:

- Code execution or file system access triggered by opening a subtitle file, project file or media file
- Exposure of API keys or other credentials stored or used by the application
- Unsafe handling of responses from translation or transcription providers

Out of scope:

- The quality or accuracy of translations and transcriptions
- Vulnerabilities in third-party providers or their services, which should be reported to the provider
- Vulnerabilities in dependencies that do not affect llm-subtrans, which should be reported upstream
