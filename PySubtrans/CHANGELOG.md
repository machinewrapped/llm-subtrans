# Changelog

All notable changes to PySubtrans will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.5.6] - 2025-10-11
Extended error handling and reporting for OpenAI reasoning model client to provide better diagnostic information.

## [1.5.5] - 2025-10-09
License fix

## [1.5.4] - 2025-10-09
Updated OpenAIReasoningClient to use properly typed parameters for compatability.

## [1.5.3] - 2025-10-03
Fixed connection of standard logger to TranslationEvents

## [1.5.2] - 2025-10-01
- Streaming response support for real-time translation updates

## [1.5.1] - 2025-09-25
- Updated documentation

## [1.5.0] - 2025-09-25
- Initial release of PySubtrans, the Subtitle translation engine powering LLM-Subtrans and GUI-Subtrans
- Integration with major LLM providers (OpenAI, Gemini, Claude, OpenRouter, DeepSeek)
- Support for multiple subtitle formats (SRT, ASS, SSA, VTT)
- Subtitle preprocessing and batching capabilities
- Persistent project support
