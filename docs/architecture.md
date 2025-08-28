# LLM-Subtrans Architecture

This document provides a high-level overview of the `llm-subtrans` project architecture. It is intended to help new developers understand how the different parts of the application fit together.

## Core Concepts

The application is divided into two main parts:

*   **`PySubtitle`**: A Python module that contains the core functionality for subtitle processing, translation, and project management.
*   **`GUI`**: A Python module that implements the graphical user interface using PySide6.

The system has two main entry points:

*   `scripts/gui-subtrans.py`: The entry point for the GUI application.
*   `scripts/llm-subtrans.py`: The entry point for the command-line interface.

## Subtitle Management

The core of the subtitle management is the `PySubtitle.SubtitleProject` class. This class represents a single translation project and is responsible for:

*   Loading subtitles from a source file (currently only `.srt` is supported).
*   Saving and loading the project state to a `.subtrans` file, which is a JSON file containing all the subtitles, their translations, and other project-related information.
*   Orchestrating the translation process.

The subtitles themselves are represented by a hierarchy of objects:

*   `PySubtitle.Subtitles`: A container for all the subtitles in a project. It holds a list of `SubtitleScene` objects.
*   `PySubtitle.SubtitleScene`: Represents a continuous scene in the video. It contains a list of `SubtitleBatch` objects.
*   `PySubtitle.SubtitleBatch`: A small group of subtitle lines that are sent to the translation provider together.
*   `PySubtitle.SubtitleLine`: Represents a single subtitle line, with its start and end times, text content, and translation.

### File Formats

Currently, the application only supports the `.srt` subtitle file format. However, the architecture is designed to be extensible, and support for other formats is planned for the future.

## Translation Process

The translation process is managed by the `PySubtitle.SubtitleTranslator` class. This class is responsible for:

*   Taking a `Subtitles` object and splitting it into scenes and batches.
*   Sending the batches to a `TranslationProvider` for translation.
*   Handling retries, error management, and post-processing of the translations.

The `SubtitleTranslator` delegates the actual translation to a `PySubtitle.TranslationProvider` instance. The `TranslationProvider` is a plug-and-play component that allows the application to support different translation services. New providers can be added by creating a new module in the `PySubtitle.Providers` directory and implementing the `TranslationProvider` interface.

## GUI Architecture

The GUI is built using PySide6 and follows a Model-View-ViewModel (MVVM) like pattern.

*   **`GUI.ViewModel.ProjectViewModel`**: This is a custom `QStandardItemModel` that serves as the data model for the various views in the GUI. It holds a tree of `SceneItem`, `BatchItem`, and `LineItem` objects, which mirror the structure of the `Subtitles` data. It has an update queue to handle asynchronous updates from the translation process, ensuring that the GUI is updated in a thread-safe manner.

*   **Views**: The GUI is composed of several views, such as the `ScenesView`, `SubtitleView`, and `LogWindow`, which are all subclasses of `QWidget`. These views are responsible for displaying the data from the `ProjectViewModel` and for handling user input.

*   **`GUI.ProjectDataModel`**: This class acts as a bridge between the core `SubtitleProject` and the `ProjectViewModel`. It holds the current project, the project options, and the current translation provider. It's responsible for creating the `ProjectViewModel` and for applying updates to it.

### Command Queue

All operations that modify the project data are encapsulated in `Command` objects and executed by a `GUI.CommandQueue`. The `CommandQueue` runs commands on a background thread, which is essential for keeping the GUI responsive during long-running operations like file I/O or translation. It also manages undo/redo stacks, allowing the user to easily revert and re-apply actions.

## Settings Management

Application settings are managed by the `PySubtitle.Options` class. This class is responsible for:

*   Loading settings from a `settings.json` file.
*   Loading settings from environment variables.
*   Providing default values for all settings.
*   Managing provider-specific settings.

The `Options` class is used throughout the application to configure the behavior of different components.
