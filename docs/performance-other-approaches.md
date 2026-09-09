**The largest opportunity is to reduce how much imported metadata participates in the interview’s normal processing.** Improving individual queries helps, but the current design makes device metadata contribute to scope resolution, condition evaluation, navigation, progress and browser state.

The [recorded benchmarks](/home/ww22buma/Next/Repos/ulb-gitlab/rdmo-plugins/rdmo-plugins-sensorsearch/docs/performance-review.md) illustrate this: refreshing 100 devices with identical metadata took about **3.97 seconds without any Value writes**. Repeated scalar-scope setup accounted for about **3.15 seconds**. These are synthetic measurements with mocked HTTP, but they point toward structural work beyond write optimization.

Here are the alternatives I would explore, from architectural changes to improvements compatible with the current storage model.

1. **Keep a metadata archive alongside a smaller set of RDMO answers.**

   Store complete, versioned device metadata in plugin-owned records. Populate RDMO Values only for information that the interview actually needs: selections, editable answers, condition inputs and essential derived fields.

   A possible division:

   | Information | Potential home |
   |---|---|
   | Selected device, human decisions, manual overrides | RDMO Values |
   | Fields used by interview conditions | RDMO Values |
   | Parameter identifiers and units needed for variable selection | Small indexed representation |
   | Extensive descriptions, contact lists, technical specifications | Versioned metadata records |
   | Deployment dates, mounting and location | Project/configuration-specific records |

   ```mermaid
   flowchart LR
       A[Device backend] --> B[Versioned metadata archive]
       B --> C[Selected fields in RDMO Values]
       C --> D[Interview and conditions]
       B --> E[Device details and exports]
       F[Project-specific answers] --> D
       F --> E
   ```

   This could use ordinary Django models with a JSON payload; a separate database service is not inherently necessary. [Django supports JSONField](https://docs.djangoproject.com/en/5.2/ref/models/fields/#jsonfield).

   **Why it could help:** fewer Values enter the generic questionnaire machinery, while full metadata remains available locally.

   **Main cost:** exports, snapshots, project copies and deletion would need explicit integration. Existing consumers that expect metadata in Values—including option providers—would need adapting. Simply packing everything into one Value and loading it on every request would miss much of the benefit.

   This is my preferred strategic direction if much of the metadata is reference material rather than something users meaningfully edit.

2. **Turn device review into a searchable inventory with details on demand.**

   Instead of presenting every device as a large repeated questionnaire block, show a compact table:

   *Device · Deployment · Metadata status · Missing information · Review status*

   Opening a device loads its details and editable fields. Users could review several devices together and focus on exceptions: missing units, conflicting dates, incomplete identifiers or failed refreshes.

   **Why it could help:** the browser handles the visible devices, and the server can fetch one configuration or device scope at a time.

   This requires both server-side scoped loading and an appropriate interface. Browser virtualization alone would not eliminate full-project database reads or answer-tree construction.

   There is also a useful product question here: should progress represent thousands of imported fields, or the decisions a person still needs to make? Changing that definition could improve both performance and usability.

3. **Defer full expansion until a deliberate documentation step.**

   A more radical variant would make the interview collect device selections and project-specific decisions first. Complete metadata would be preserved as a local revision, then included in a generated appendix or expanded into standard Values when the user finalizes the documentation.

   **Why it could help:** ordinary editing stays small even when the final document is comprehensive.

   **Tradeoff:** this changes when the full representation becomes available. It fits an interview whose output is a report better than one where every imported field must remain an ordinary editable RDMO answer. Exports should use the pinned local revision, so their contents do not depend on the backend’s availability or latest state.

4. **Build the refresh plan once for the entire device batch.**

   This is the strongest next experiment while keeping the current data model.

   The current [scalar-scope resolver](/home/ww22buma/Next/Repos/ulb-gitlab/rdmo-plugins/rdmo-plugins-sensorsearch/rdmo_sensorsearch/persistence/value_reconciliation.py:23) loads current project Values and constructs AnswerTree lookup state per mapped result. A batch refresh could instead:

   - Resolve catalog structure once.
   - Establish the required device and collection scopes.
   - Build one project scope index.
   - Plan and apply changes for all refreshed devices against that shared state.

   **Why it could help:** it targets the repeated setup dominating the identical-metadata refresh benchmark.

   The difficult part is correctness during mutations. Reusing an index blindly would be unsafe when earlier devices create or remove scopes. A two-phase approach—establish structure, then reconcile fields—or an explicitly maintained index would be necessary.

5. **Make interview computation depend on what changed.**

   In the checked-out core, [navigation, progress and page resolution](/home/ww22buma/Next/Repos/ulb-gitlab/rdmo/rdmo/projects/progress.py:1) each request an answer tree. The [condition-resolution endpoint](/home/ww22buma/Next/Repos/ulb-gitlab/rdmo/rdmo/projects/viewsets.py:268) also loads all current project Values when it has conditions to evaluate.

   An alternative would maintain a catalog dependency map:

   > Attribute changed → affected conditions → affected pages and progress counts.

   A descriptive metadata update might affect no interview conditions at all. Adding a device scope could require a wider update. These should have different computational costs.

   **A smaller first step:** load only the attributes needed by the requested conditions, preserving scope inheritance and providing a fallback for conditions whose dependencies cannot be determined.

   **A larger step:** maintain per-page visibility and completion state and invalidate only affected entries. This requires careful handling of imports, catalog changes and custom conditions, but would benefit large RDMO projects beyond this plugin.

6. **Treat one save as one interview update.**

   The frontend currently [dispatches navigation and progress updates after saving](/home/ww22buma/Next/Repos/ulb-gitlab/rdmo/rdmo/projects/assets/js/interview/actions/interviewActions.js:324), alongside condition resolution or refreshed Values.

   An alternative API could return a single consistent update containing changed Values, condition results, navigation changes and progress. The server could reuse one computation context rather than reconstruct related state across separate requests.

   **Why it could help:** less duplicate work, fewer requests and fewer opportunities for responses from different project states to arrive out of order.

   There is also a smaller browser-side candidate: the [refresh merge](/home/ww22buma/Next/Repos/ulb-gitlab/rdmo/rdmo/projects/assets/js/interview/actions/interviewActions.js:193) searches fetched Values with `.find()` for each existing Value. An indexed lookup could remove that potentially quadratic operation, provided it preserves the existing identity comparison and unsaved-input behavior.

7. **Refresh immutable metadata revisions and reuse them.**

   Several projects may use the same device. They could reference a shared immutable metadata revision rather than repeatedly fetching and storing identical intrinsic facts.

   Project-specific deployment information must remain separate: the same device can have different mounting, location and usage periods. Reuse must also respect backend access permissions, and refreshing one project must not silently change another project’s pinned revision.

   Where the backend supports ETags or modification timestamps, conditional requests could avoid transferring unchanged metadata. Locally, a normalized-content fingerprint could skip reconciliation—but it must also account for mapping changes and missing or edited generated Values. “Check for backend changes” and “repair generated answers” are different operations.

   For RDMO responses, a cheap revision check **before** constructing the response could similarly avoid unnecessary work. Django’s ordinary conditional middleware only saves response transfer; its early conditional-processing mechanism can skip expensive view execution. [Django conditional processing](https://docs.djangoproject.com/en/5.2/topics/conditional-view-processing/).

8. **Represent synchronization as an explicit operation.**

   A selection change or configuration refresh could create one synchronization operation covering all affected devices. That operation would fetch metadata, compute a combined difference, apply changes and issue one interview update.

   This could reduce the amplification caused by inferring work separately from individual Value signals, particularly during deletion and collection changes.

   A background worker is an optional extension. It would release the web request and enable progress reporting, but would not itself reduce total processing. It also changes the synchronous behavior preserved by the approved implementation, so I would treat it as a separate design decision. Operation revisions would be needed to prevent an older refresh from overwriting a newer selection.

**I would start with three bounded experiments:**

| Experiment | What it would establish |
|---|---|
| One scope index for a complete refresh | How much of the measured refresh cost can disappear without changing storage |
| Condition reads limited to their dependencies | Whether unrelated metadata can stop affecting ordinary interview edits |
| One metadata category moved to a versioned archive, with a device detail view | Whether a smaller questionnaire representation delivers enough benefit to justify migration and export integration |

Measure end-to-end edit latency, response size, browser rendering, memory and correctness alongside SQL counts. My strongest long-term candidate is **a compact interview backed by a complete versioned metadata archive**; the batch scope index is the most directly supported next optimization in the existing design.
