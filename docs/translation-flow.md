# Translation Request Flow

This document provides detailed mermaid diagrams showing how a translation request flows through the LLM-Subtrans GUI application, from user action to UI update.

## Overview

The translation flow follows this high-level path:
1. User triggers translation via `ProjectActions.StartTranslating()`
2. Command is queued in `CommandQueue`
3. Commands execute on background threads
4. Commands emit `ModelUpdate` objects during execution
5. `ProjectDataModel` receives and queues updates
6. `ProjectViewModel` processes updates on main thread
7. Qt views automatically refresh to show changes

## 1. Sequence Diagram: Full Translation Flow

```mermaid
sequenceDiagram
    participant User
    participant ProjectActions
    participant CommandQueue
    participant StartTranslationCommand
    participant TranslateSceneCommand
    participant SubtitleTranslator
    participant ProjectDataModel
    participant ProjectViewModel
    participant Views

    User->>ProjectActions: StartTranslating()
    ProjectActions->>ProjectActions: _validate_datamodel()
    ProjectActions->>ProjectActions: saveSettings.emit()

    ProjectActions->>CommandQueue: QueueCommand(StartTranslationCommand)
    Note over CommandQueue: Command added to queue<br/>and thread pool

    CommandQueue->>StartTranslationCommand: execute()
    Note over StartTranslationCommand: Creates TranslateSceneCommand<br/>for each scene

    loop For each scene
        StartTranslationCommand->>CommandQueue: commands_to_queue.append(TranslateSceneCommand)
    end

    CommandQueue->>TranslateSceneCommand: execute() [background thread]
    TranslateSceneCommand->>SubtitleTranslator: new SubtitleTranslator()
    TranslateSceneCommand->>SubtitleTranslator: Connect event handlers
    TranslateSceneCommand->>SubtitleTranslator: TranslateScene()

    loop For each batch in scene
        SubtitleTranslator->>SubtitleTranslator: Translate batch
        SubtitleTranslator-->>TranslateSceneCommand: batch_updated event (streaming)
        TranslateSceneCommand->>TranslateSceneCommand: Create ModelUpdate
        TranslateSceneCommand->>ProjectDataModel: UpdateViewModel(ModelUpdate)
        ProjectDataModel->>ProjectViewModel: AddUpdate(lambda)
        Note over ProjectViewModel: Update queued with mutex
        ProjectViewModel-->>ProjectDataModel: updatesPending signal

        SubtitleTranslator-->>TranslateSceneCommand: batch_translated event (complete)
        TranslateSceneCommand->>TranslateSceneCommand: Create ModelUpdate
        TranslateSceneCommand->>ProjectDataModel: UpdateViewModel(ModelUpdate)
        ProjectDataModel->>ProjectViewModel: AddUpdate(lambda)
        ProjectViewModel-->>ProjectDataModel: updatesPending signal
    end

    Note over ProjectViewModel: Main thread processes updates
    ProjectViewModel->>ProjectViewModel: ProcessUpdates()

    loop While updates pending
        ProjectViewModel->>ProjectViewModel: Pop update from queue
        ProjectViewModel->>ProjectViewModel: ApplyUpdate(update_function)
        ProjectViewModel->>ProjectViewModel: update_function(self)
        Note over ProjectViewModel: ModelUpdate.ApplyToViewModel()<br/>modifies SceneItem/BatchItem/LineItem
        ProjectViewModel->>ProjectViewModel: Remap()
        ProjectViewModel-->>Views: layoutChanged signal
    end

    Views->>Views: Refresh display
    Note over Views: Qt model/view framework<br/>automatically updates
```

## 2. Class Diagram: Key Components

```mermaid
classDiagram
    class ProjectActions {
        -CommandQueue _command_queue
        -ProjectDataModel datamodel
        +StartTranslating()
        +QueueCommand(Command)
        -_validate_datamodel()
    }

    class CommandQueue {
        -list~Command~ queue
        -list~Command~ undo_stack
        -QThreadPool command_pool
        -QRecursiveMutex mutex
        +AddCommand(Command)
        +ExecuteCommand(Command)
        -_queue_command(Command)
        -_start_command_queue()
    }

    class Command {
        <<abstract>>
        #ProjectDataModel datamodel
        #list~Command~ commands_to_queue
        #bool started
        #bool succeeded
        +execute() bool
        +commandCompleted Signal
    }

    class StartTranslationCommand {
        -bool multithreaded
        -bool resume
        -dict scenes
        +execute() bool
    }

    class TranslateSceneCommand {
        -int scene_number
        -list~int~ batch_numbers
        -SubtitleTranslator translator
        -set processed_lines
        +execute() bool
        -_on_batch_translated(batch)
        -_on_batch_updated(batch)
    }

    class SubtitleTranslator {
        +TranslationEvents events
        +TranslateScene(subtitles, scene)
        -_translate_batch(batch)
    }

    class ProjectDataModel {
        +SubtitleProject project
        +ProjectViewModel viewmodel
        +Options project_options
        +TranslationProvider translation_provider
        -QRecursiveMutex mutex
        +UpdateViewModel(ModelUpdate)
        +CreateViewModel() ProjectViewModel
    }

    class ProjectViewModel {
        -dict~int,SceneItem~ model
        -list~Callable~ updates
        -QRecursiveMutex update_lock
        +updatesPending Signal
        +AddUpdate(Callable)
        +ProcessUpdates()
        +ApplyUpdate(update_function)
        +UpdateScene(number, update)
        +UpdateBatch(scene, batch, update)
        +UpdateLines(scene, batch, lines)
    }

    class ModelUpdate {
        +ModelUpdateSection scenes
        +ModelUpdateSection batches
        +ModelUpdateSection lines
        +ApplyToViewModel(ProjectViewModel)
        +has_update bool
    }

    class ModelUpdateSection {
        +dict updates
        +dict additions
        +list removals
        +dict replacements
        +has_updates bool
        +update(key, data)
    }

    ProjectActions --> CommandQueue : uses
    ProjectActions --> ProjectDataModel : accesses
    CommandQueue --> Command : manages
    Command <|-- StartTranslationCommand : extends
    Command <|-- TranslateSceneCommand : extends
    StartTranslationCommand --> TranslateSceneCommand : creates
    TranslateSceneCommand --> SubtitleTranslator : uses
    TranslateSceneCommand --> ModelUpdate : creates
    TranslateSceneCommand --> ProjectDataModel : updates
    ProjectDataModel --> ProjectViewModel : owns
    ProjectDataModel --> ModelUpdate : receives
    ModelUpdate --> ModelUpdateSection : contains
    ModelUpdate --> ProjectViewModel : updates
```

## 3. State Diagram: Command Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Created : new Command()
    Created --> Queued : AddCommand()

    Queued --> Started : Thread available
    Started --> Executing : execute()

    Executing --> EmittingUpdates : Translation in progress
    EmittingUpdates --> EmittingUpdates : For each batch

    note right of EmittingUpdates
        Creates ModelUpdate objects
        Sends to ProjectDataModel
        Updates queued in ViewModel
    end note

    EmittingUpdates --> Completed : All batches done
    Completed --> AddedToUndoStack : If not skip_undo
    AddedToUndoStack --> [*]

    Executing --> Aborted : StopTranslating()
    Aborted --> [*]

    Executing --> Failed : Exception thrown
    Failed --> [*]
```

## 4. Data Flow Diagram: ModelUpdate Processing

```mermaid
flowchart TD
    A[TranslateSceneCommand executing] --> B{Batch translation event?}

    B -->|batch_updated| C[Create ModelUpdate]
    B -->|batch_translated| C

    C --> D[ModelUpdate.batches.update]
    D --> E[Set batch properties:<br/>- summary<br/>- context<br/>- errors<br/>- lines]

    E --> F[ProjectDataModel.UpdateViewModel]
    F --> G{Has viewmodel?}

    G -->|Yes| H[viewmodel.AddUpdate with lambda]
    G -->|No| Z[Skip update]

    H --> I[Lock update_lock]
    I --> J[Append to updates list]
    J --> K[Release lock]
    K --> L[Emit updatesPending signal]

    L --> M[Main thread: ProcessUpdates]
    M --> N[Lock update_lock]
    N --> O{Updates in queue?}

    O -->|Yes| P[Pop next update]
    O -->|No| Q[Done processing]

    P --> R[Release lock]
    R --> S[Call update lambda]
    S --> T[ModelUpdate.ApplyToViewModel]

    T --> U{Reset needed?}
    U -->|Yes - has additions/removals| V[beginResetModel]
    U -->|No| W[Skip reset]

    V --> X[Apply scene updates]
    W --> X

    X --> Y[Apply batch updates]
    Y --> AA[Apply line updates]

    AA --> AB{Was reset begun?}
    AB -->|Yes| AC[endResetModel]
    AB -->|No| AD[Skip end reset]

    AC --> AE[SetLayoutChanged]
    AD --> AE

    AE --> AF[Remap viewmodel]
    AF --> AG{Layout changed?}

    AG -->|Yes| AH[Emit layoutChanged]
    AG -->|No| AI[Skip signal]

    AH --> M
    AI --> M

    Q --> AJ[Views refresh automatically<br/>via Qt model/view]
    AJ --> AK[End]
```

## 5. Component Interaction Diagram

```mermaid
flowchart LR
    subgraph "Main Thread"
        PA[ProjectActions]
        VM[ProjectViewModel]
        V[Views]
    end

    subgraph "Command Queue Thread Pool"
        CQ[CommandQueue]

        subgraph "Command Execution"
            STC[StartTranslationCommand]
            TSC1[TranslateSceneCommand 1]
            TSC2[TranslateSceneCommand 2]
            TSCN[TranslateSceneCommand N]
        end

        subgraph "Translation Engine"
            ST1[SubtitleTranslator 1]
            ST2[SubtitleTranslator 2]
            STN[SubtitleTranslator N]
        end
    end

    subgraph "Data Layer"
        PDM[ProjectDataModel]
        SP[SubtitleProject]
        SUB[Subtitles]
    end

    PA -->|QueueCommand| CQ
    CQ -->|Execute| STC
    STC -->|Creates| TSC1
    STC -->|Creates| TSC2
    STC -->|Creates| TSCN

    TSC1 -->|Uses| ST1
    TSC2 -->|Uses| ST2
    TSCN -->|Uses| STN

    TSC1 -->|ModelUpdate| PDM
    TSC2 -->|ModelUpdate| PDM
    TSCN -->|ModelUpdate| PDM

    PDM -->|Owns| SP
    PDM -->|Owns| VM
    SP -->|Contains| SUB

    PDM -->|AddUpdate| VM
    VM -->|updatesPending signal| VM
    VM -->|layoutChanged signal| V

    ST1 -.->|Reads/Writes| SUB
    ST2 -.->|Reads/Writes| SUB
    STN -.->|Reads/Writes| SUB
```

## 6. Detailed ModelUpdate Processing

```mermaid
flowchart TD
    A[ModelUpdate created] --> B{Check update type}

    B -->|Scene update| C[scenes.update]
    B -->|Batch update| D[batches.update]
    B -->|Line update| E[lines.update]

    C --> F[Key: scene_number]
    D --> G[Key: scene_number, batch_number]
    E --> H[Key: scene_number, batch_number, line_number]

    F --> I[Data: dict with properties]
    G --> I
    H --> I

    I --> J[ModelUpdate.ApplyToViewModel]

    J --> K{Processing scenes}
    K -->|replacements| L[viewmodel.ReplaceScene]
    K -->|updates| M[viewmodel.UpdateScene]
    K -->|removals| N[viewmodel.RemoveScene]
    K -->|additions| O[viewmodel.AddScene]

    L --> P{Processing batches}
    M --> P
    N --> P
    O --> P

    P -->|replacements| Q[viewmodel.ReplaceBatch]
    P -->|updates| R[viewmodel.UpdateBatch]
    P -->|removals| S[viewmodel.RemoveBatch]
    P -->|additions| T[viewmodel.AddBatch]

    Q --> U{Processing lines}
    R --> U
    S --> U
    T --> U

    U -->|updates| V[GetUpdatedLinesInBatches]
    U -->|removals| W[GetRemovedLinesInBatches]
    U -->|additions| X[viewmodel.AddLine]

    V --> Y[Group by scene, batch]
    W --> Y

    Y --> Z[viewmodel.UpdateLines]
    Z --> AA[Update SceneItem]
    X --> AA

    AA --> AB[Update BatchItem]
    AB --> AC[Update LineItem]
    AC --> AD[Set item data]
    AD --> AE[Qt item updated]
```

## Key Implementation Details

### Thread Safety

1. **CommandQueue** uses `QRecursiveMutex` to protect the command queue and undo/redo stacks
2. **ProjectViewModel** uses `QRecursiveMutex` to protect the updates list
3. **ProjectDataModel** uses `QRecursiveMutex` for thread-safe access to project data
4. Updates are queued on background threads but processed on the main thread via signals

### Update Batching

- **Streaming updates** (`batch_updated` events) send incremental line translations as they arrive
- **Complete updates** (`batch_translated` events) send full batch data including metadata
- `TranslateSceneCommand` tracks processed lines to avoid redundant updates

### Model Reset Strategy

- **Nuclear option**: When `ModelUpdate` contains additions or removals, the entire model is reset
- This prevents Qt crashes from dangling indexes
- For simple updates (property changes), items are updated in place without reset

### Signal Flow

1. `CommandQueue.commandExecuted` - when command completes
2. `ProjectViewModel.updatesPending` - when updates are queued
3. `ProjectViewModel.layoutChanged` - when structure changes require view refresh
4. Qt's model/view framework automatically refreshes views on these signals

## Common Patterns

### Pattern 1: Simple Property Update

```python
# In TranslateSceneCommand._on_batch_translated
update = ModelUpdate()
update.batches.update((batch.scene, batch.number), {
    'summary': batch.summary,
    'context': batch.context
})
self.datamodel.UpdateViewModel(update)
```

### Pattern 2: Line Translation Updates

```python
# Update multiple lines in a batch
update = ModelUpdate()
update.batches.update((batch.scene, batch.number), {
    'lines': {
        line.number: {'translation': line.text}
        for line in batch.translated
    }
})
self.datamodel.UpdateViewModel(update)
```

### Pattern 3: Scene-level Update

```python
# Update scene summary after translation
model_update = self.AddModelUpdate()
model_update.scenes.update(scene.number, {
    'summary': scene.summary
})
```

## Error Handling

- **TranslationAbortedError** marks command as aborted and terminal
- **TranslationImpossibleError** logs error and marks command as terminal
- **ProviderError** / **NoProviderError** mark the command terminal - a provider that cannot produce a client will fail identically for every other scene
- An exception that escapes `execute()` is caught by `Command.run()`, which sets `succeeded = False`, and `terminal = True` for a `CommandError`. Commands that can recognise a fatal error should handle it themselves, as `TranslateSceneCommand` does
- Terminal commands prevent subsequent queued commands from executing, but still report whether their own work succeeded - `terminal` is about what follows, not about this command's result
- Undo stack is cleared when non-undoable commands execute

## Performance Considerations

1. **Multithreading**: Multiple scenes can be translated in parallel when `multithreaded=True`
2. **Update batching**: ViewModel queues updates and processes them in sequence on main thread
3. **Incremental updates**: Streaming updates provide real-time feedback without blocking
4. **Smart remapping**: ViewModel only remaps when structure changes occur
5. **Mutex granularity**: Fine-grained locking minimizes contention between threads
