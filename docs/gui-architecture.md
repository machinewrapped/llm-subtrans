# GUI Architecture

This guide maps the desktop GUI components and explains how queued commands update the visible project. For the full translation-specific sequence and state diagrams, see [translation-flow.md](translation-flow.md).

## Component Map

~~~mermaid
flowchart TD
    MainWindow --> GuiInterface
    MainWindow --> ModelView
    GuiInterface --> ProjectActions
    GuiInterface --> CommandQueue
    GuiInterface --> ProjectDataModel
    ProjectActions -->|queue command| CommandQueue
    CommandQueue -->|schedule| Commands
    Commands -->|ModelUpdate| ProjectDataModel
    ProjectDataModel -->|owns| ProjectViewModel
    ProjectViewModel --> ScenesBatchesModel --> ScenesView
    ProjectViewModel --> SubtitleListModel --> SubtitleView
    ModelView --> ScenesView
    ModelView --> ContentView
    ContentView --> SubtitleView
    ContentView --> SelectionView
    ModelView --> ProjectSettings
~~~

### Main Components

| Component | Location | Responsibility |
|-----------|----------|----------------|
| MainWindow and GuiInterface | GuiSubtrans/MainWindow.py, GuiSubtrans/GuiInterface.py | Assemble the application window and connect actions, project state, commands, and widgets |
| ProjectActions | GuiSubtrans/ProjectActions.py | Turn GUI actions into project operations and queued commands |
| CommandQueue and Command | GuiSubtrans/CommandQueue.py, GuiSubtrans/Command.py | Schedule background work, track command lifecycle, and manage undo/redo |
| ProjectDataModel | GuiSubtrans/ProjectDataModel.py | Own the active project, project options, provider, and ProjectViewModel |
| ProjectViewModel and ModelUpdate | GuiSubtrans/ViewModel/ | Represent scenes, batches, and lines for Qt views and apply queued changes |
| Project widgets | GuiSubtrans/Widgets/ | Display the scene tree, selected subtitle content, settings, and logs |

## Command Queue

Most GUI operations that load, save, translate, transcribe, or edit project data are represented by a Command subclass under GuiSubtrans/Commands/.

1. A widget or toolbar action calls ProjectActions, which supplies the active ProjectDataModel to the command and adds it to CommandQueue.
2. CommandQueue schedules command work through a QThreadPool. Its default thread limit is one; the limit can be raised, and blocking commands prevent other queued work from starting alongside them.
3. A command reports its start and completion to the queue. The queue runs completion callbacks, records successful undoable commands, and schedules any follow-up commands.
4. Follow-up commands inherit their parent's data model by default. A standalone file operation can opt out of data-model updates so its completion does not replace the active GUI project.

The queue also owns undo and redo history. Commands define which operations can be undone and whether successful execution marks the project as needing a save.

## How Model Updates Reach the Views

Commands that change visible project state build a ModelUpdate containing scene, batch, or line changes. The update path is:

1. The command calls ProjectDataModel.UpdateViewModel() with the update.
2. ProjectDataModel wraps it as an operation on the active ProjectViewModel and queues it with ProjectViewModel.AddUpdate().
3. AddUpdate() appends the operation to a mutex-protected queue and emits updatesPending.
4. ContentView receives that signal through a queued Qt connection and calls ProcessUpdates() on the GUI thread.
5. ModelUpdate.ApplyToViewModel() applies the scene, batch, and line changes. Additions and removals reset the Qt model; ordinary property changes update existing items. The view model remaps its item lookup and emits model signals when the layout changes.
6. ScenesView and SubtitleView observe the shared view model through ScenesBatchesModel and SubtitleListModel. Qt's model/view signals refresh the widgets after the update is applied.

The command worker sends data changes through this queue instead of modifying Qt view-model items directly. This keeps view-model mutations on the GUI thread.

## View Structure

MainWindow contains the application toolbar, project toolbar, project view, project settings, and log window.

ModelView organizes project settings, ScenesView, and ContentView in a splitter. ScenesView displays scenes and batches. ContentView combines SubtitleView for the selected subtitle lines with SelectionView for contextual actions. Editors in GuiSubtrans/Widgets/Editors.py submit accepted changes through ProjectActions.

ProjectViewModel mirrors the data hierarchy as SceneItem, BatchItem, and LineItem. ScenesView and SubtitleView use small Qt model adapters to show different projections of that shared hierarchy.

Global and provider settings are presented by SettingsDialog; project-level settings are presented by ProjectSettings. Provider option schemas and asynchronous model loading are described in [translation-provider-integration.md](translation-provider-integration.md).

## Related Guides

- [translation-flow.md](translation-flow.md) - detailed translation command sequence, lifecycle, and update diagrams
- [translation-provider-integration.md](translation-provider-integration.md) - provider-specific settings and model loading
- [architecture.md](architecture.md) - application-wide component map