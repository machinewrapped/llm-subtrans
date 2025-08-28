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

## GUI View and Widget Architecture

The GUI's view and widget architecture is designed to be modular and extensible. It is built upon the `ProjectViewModel`, which provides the data for the various views.

### The `ModelView`

The central widget for displaying project data is the `GUI.Widgets.ModelView`. It is a container widget that uses a `QSplitter` to arrange three main components:

*   **`GUI.Widgets.ProjectSettings`**: A form for editing project-specific settings. It is displayed when the user clicks on the "Settings" button in the `ProjectToolbar`.
*   **`GUI.Widgets.ScenesView`**: A `QTreeView` that displays the scenes and batches from the `ProjectViewModel`.
*   **`GUI.Widgets.ContentView`**: A container widget that holds the `SubtitleView` and the `SelectionView`.

### Core Views

*   **`GUI.Widgets.ScenesView`**: This `QTreeView` provides a hierarchical view of the scenes and batches in the project. It uses a custom `GUI.ScenesBatchesModel` and `GUI.ScenesBatchesDelegate` to render the items. It allows for selection of scenes and batches, and for editing them by double-clicking.

*   **`GUI.Widgets.ContentView`**: This widget is the main area for interacting with the subtitles. It contains:
    *   **`GUI.Widgets.SubtitleView`**: A `QListView` that displays the subtitle lines for the selected scenes or batches. It uses a custom `GUI.SubtitleListModel` and `GUI.SubtitleItemDelegate` to render the lines. It supports selection and editing of individual lines.
    *   **`GUI.Widgets.SelectionView`**: A `QFrame` that displays information about the current selection (scenes, batches, or lines) and provides contextual actions. The buttons in this view are dynamically shown or hidden based on the current selection.

### Editors and Dialogs

*   **`GUI.Widgets.Editors`**: This module contains various dialogs for editing scenes, batches, and individual subtitle lines. These dialogs are launched when a user double-clicks on an item in the `ScenesView` or `SubtitleView`. They are built dynamically based on the data in the selected item.

### Reusable Widgets

*   **`GUI.Widgets.OptionsWidgets`**: This module provides a set of reusable widgets for editing different types of options (e.g., `TextOptionWidget`, `CheckboxOptionWidget`, `DropdownOptionWidget`). These are used to construct the forms in `ProjectSettings` and the main `SettingsDialog`.

*   **`GUI.Widgets.Widgets`**: This module contains a collection of custom widgets used to build the user interface, such as `TreeViewItemWidget` for rendering items in the `ScenesView`, and `LineItemView` for rendering items in the `SubtitleView`. These widgets help to create a consistent and visually appealing user interface.