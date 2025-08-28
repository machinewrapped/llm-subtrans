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

### The `SettingsDialog`

The `GUI.SettingsDialog` is a powerful example of a data-driven user interface in the application. It is responsible for allowing users to edit the application's settings. The dialog is built dynamically based on a dictionary-based configuration, which makes it easy to add new settings and options without having to write a lot of boilerplate UI code.

#### Data-Driven UI Generation

The structure of the `SettingsDialog` is defined by the `SECTIONS` dictionary. This dictionary maps tab names (e.g., "General", "Processing") to a nested dictionary of setting keys and their types. For example:

```python
'General': {
    'ui_language': (str, _("The language of the application interface")),
    'theme': [],
    'target_language': (str, _("The default language to translate the subtitles to")),
    # ...
},
```

The dialog iterates over this dictionary and uses the `GUI.Widgets.OptionsWidgets.CreateOptionWidget` factory function to create the appropriate widget for each setting based on its type (`str`, `int`, `float`, `bool`, or a list for a dropdown). This approach makes the dialog highly extensible and easy to maintain.

#### Dynamic Provider Settings

A key feature of the `SettingsDialog` is its ability to display settings for the currently selected `TranslationProvider`. The "Provider Settings" tab is populated dynamically by calling the `GetOptions` method on the active `TranslationProvider` instance. This method returns a dictionary of settings that are specific to that provider.

This allows each translation provider to define its own set of options, which are then automatically displayed in the settings dialog when that provider is selected. This is a great example of the "plug-and-play" architecture of the translation providers.

#### Conditional Visibility

The `SettingsDialog` also uses a data-driven approach to manage the visibility of certain settings. The `VISIBILITY_DEPENDENCIES` dictionary defines the conditions under which a setting should be visible. For example, the `max_single_line_length` option is only visible if `postprocess_translation` and `break_long_lines` are both enabled. This is achieved by checking the values of the settings and showing or hiding the corresponding widgets accordingly. This makes the UI cleaner and more intuitive for the user.

### Command Queue and Execution

The application uses a command queue to manage all operations that modify the project data. This ensures that long-running operations are executed on a background thread, keeping the GUI responsive. The command queue system is also responsible for managing the undo/redo functionality.

#### The `GuiInterface`

The `GUI.GuiInterface` class is the central hub for the command queue system. It is responsible for:

*   **Creating and managing the `CommandQueue`**: The `GuiInterface` creates a single instance of the `CommandQueue` and connects to its signals (`commandStarted`, `commandExecuted`, `commandAdded`, `commandUndone`). This allows the `GuiInterface` to monitor the state of the command queue and to react to command events.

*   **Providing access to the `CommandQueue`**: The `GuiInterface` provides a `QueueCommand` method that allows other parts of the GUI to add commands to the queue. This is the primary way that the GUI interacts with the command queue.

*   **Wiring up signals and callbacks**: The `GuiInterface` connects signals from the `ProjectActions` handler to the appropriate slots for creating and queueing commands.

#### The `CommandQueue`

The `GUI.CommandQueue` is the heart of the command execution system. It is responsible for:

*   **Managing a queue of commands**: The `CommandQueue` maintains a queue of `Command` objects and executes them sequentially on a background thread pool (`QThreadPool`).

*   **Handling command execution**: The `CommandQueue` ensures that only one command is executed at a time (or more, if multithreading is enabled for specific commands). It also handles blocking commands, which prevent other commands from running in parallel.

*   **Managing undo and redo stacks**: The `CommandQueue` maintains two stacks of commands: an undo stack and a redo stack. When a command is executed, it is pushed onto the undo stack. If the user chooses to undo the command, it is moved from the undo stack to the redo stack.

#### The `Command` Class

The `GUI.Command.Command` class is the base class for all commands in the application. Each command encapsulates a single unit of work, such as loading a file, translating a batch of subtitles, or merging lines.

Key features of the `Command` class include:

*   **`execute()` method**: Each command must implement an `execute` method, which contains the logic for the command. This method is called by the `CommandQueue` when the command is executed.

*   **`undo()` method**: Commands can also implement an `undo` method, which contains the logic for reversing the command's effects. This method is called by the `CommandQueue` when the user chooses to undo the command.

*   **Model Updates**: Commands can generate `ModelUpdate` objects, which are used to update the `ProjectViewModel` in a thread-safe manner. This ensures that the GUI is always in sync with the project data.

*   **Callbacks**: Commands can have callbacks that are executed when the command is completed or undone. This allows for a flexible and decoupled way of handling the results of a command.