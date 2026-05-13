Validity Gates in Ultimate Pipeline

The ultimate_pipeline system incorporates a series of validity gates that act as explicit control points within the processing workflow. These gates prevent known failure modes from propagating silently through the pipeline and ensure that experimental outcomes remain interpretable and reproducible.

The import-time side-effect gate addresses failures caused by unintended execution during module import. This gate prevents test execution from being disrupted by argument parsing or side effects that occur before runtime control is established. Failure at this gate is indicated by import-time exceptions during test collection, and its presence ensures that the pipeline can be safely evaluated in isolation from execution context.

The CARLA availability gate verifies simulator accessibility before CARLA-dependent steps are executed. This gate prevents the pipeline from entering undefined states caused by unavailable or unresponsive simulator instances. Connection refusal or timeout signals indicate failure at this gate. By explicitly checking simulator readiness, the pipeline avoids ambiguous outcomes caused by partial or failed simulator interaction.

The OpenDRIVE validity gate ensures that generated OpenDRIVE files conform to constraints required for stable CARLA execution. This gate captures structural inconsistencies, such as invalid road marking definitions, before simulation. Validation failures serve as the signal for gate failure, preventing simulator crashes that would otherwise obscure the underlying cause.

The tiling QA gate, controlled through ENABLE_TILE_QA, governs optional quality assurance checks that depend on simulator interaction. When disabled, tiling artifacts are still produced deterministically without invoking CARLA. Failures at this gate are reported explicitly rather than causing abrupt termination. This separation preserves artifact generation while allowing controlled simulator-dependent validation.

Collectively, these validity gates improve reproducibility by ensuring that failures are detected early, classified correctly, and recorded consistently. Each gate transforms a potential runtime failure into a measurable experimental signal, strengthening the interpretability and reliability of results produced by ultimate_pipeline.
