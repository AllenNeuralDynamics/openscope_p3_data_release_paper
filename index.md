---
title: OpenScope Predictive Processing Community Project - Data Release
---

:::{warning} Author list not final
The displayed author list and author order are provisional and will be finalized before manuscript submission.

**[Add or update your authorship contribution](https://data.allenneuraldynamics.org/contributions/add?project=p3_data_release).**
:::

:::{authorship-explorer}
:authors: ./authors.yml
:height: 800px
:::

:::{note} Manuscript status
Incomplete prose, analysis outlines, and placeholder figures are labeled **Work in progress**. Specific missing details are highlighted in amber. Unmarked material represents the current manuscript content.
:::

# Abstract

:::{warning} Work in progress
:class: manuscript-wip
The abstract has not yet been drafted.
:::

# Background & Rationale

:::{figure} ./images/figures/generated/figure-01-overview.svg
:label: fig-graphical-abstract
:alt: Predictive-processing computations across spatial scales, the multimodal experimental workflow, and context allocation across recording cohorts.
:width: 100%

Distributed predictive-processing hypotheses motivate multimodal recordings. **A,** A visual sequence establishes an expectation (blue), whereas an unexpected oddball produces a prediction-error signal (red). Predictions and errors may be expressed through reciprocal brain-wide pathways, within local cortical populations, and across the dendritic and somatic compartments of individual neurons. **B,** To sample these nested scales within one standardized project, animals progressed from surgery through intrinsic-signal-imaging mapping and habituation before recording with mesoscope two-photon imaging, Neuropixels electrophysiology, or SLAP2 dendritic imaging. **C,** Five cohort timelines show eight outlined habituation and training sessions followed by filled neural-recording sessions. Neuropixels and mesoscope sampled motor- and sequence-habituated cohorts in opposite context orders. Neuropixels sampled every context once, whereas mesoscope repeated each context twice; SLAP2 sampled the motor-habituated cohort only.
:::

## The challenge of predictive processing research

Predictive processing theories propose that the brain continuously generates predictions about incoming sensory signals and updates its internal models when those predictions are violated. These prediction errors are thought to drive perception, learning, and behavior. While this framework has gained considerable theoretical support, significant conflicts persist in the experimental literature regarding the neural mechanisms that implement predictive computations.

:::{warning} Work in progress
:class: manuscript-wip
This subsection still needs additional synthesis of the unresolved conceptual challenges in predictive-processing research.
:::

## Relationship to the companion review

This data release follows up a community review paper which synthesizes the theoretical motivations, identifies the key convergences and divergences in the predictive processing literature, and details the experimental hypotheses that this dataset was designed to test. Specifically, the dataset allows testing of two overarching alternative hypotheses: (H0) that different types of prediction errors involve fundamentally distinct neural mechanisms with specialized circuits for each type, or (H1) that a common computational principle underlies all mismatch responses, with apparent differences reflecting implementation variations.

## What gap this dataset fills

A recent (May 6, 2026) database search on PubMed using the Boolean search: “predictive processing” OR “predictive coding”, returned more than 3,000 peer-reviewed publications (3,166). A thorough meta-analysis of such a large amount of scientific literature is arguably beyond the capability of any individual scientist. Recently, a group of more than 60 experts in the field thus aimed to collectively review this research corpus [@aizenbud2026neural]. A main finding of this collective effort was that the concept of predictive processing has given rise to multiple, loosely overlapping research fields that differ both in research methodology as well as experimental paradigms. That is, experimental studies on predictive processing range in scope from measurements of single neurons to full brain studies, giving rise to computational models that range from single synapses to large neuronal networks. And, at the same time, experimental studies on predictive processing use a large variety of different stimuli, giving rise to a variety of computational models that support some but not other paradigms. As a consequence, research on predictive processing has grown fragmented both methodologically and conceptually. This fragmentation produced a multitude of gaps in the research landscape that collectively impede coherent assessment of the current state of the art of predictive processing as a whole.

Our dataset was designed to fill these gaps by creating a bridge across both these dimensions (methods and stimuli) in an attempt to unify these divergent approaches. The aim is rigorous evaluation and study of predictive processing across experimental paradigms and neuroscientific methodologies. More specifically, as discussed below, we employed 4 of the most commonly used stimulus designs across 2 of the most commonly used techniques (electrophysiology and neuroimaging). On top of that, we added single vesicle glutamate imaging (SLAP2) to expand spatial coverage from multiple brain areas down to singular synaptic spines, or from multi-area computations down to single neuron computations. Each of these methodological modalities were performed *in vivo* using the same standardized experimental paradigm and stimuli.

### Cross-context comparability

Existing studies of prediction errors typically employ only one class of mismatch stimulus (e.g., orientation oddball or visuomotor mismatch) in isolation, making it impossible to determine whether the observed neural responses reflect a general prediction error mechanism or a stimulus-specific computation. Our experimental design presents four distinct types of prediction violations (standard oddball, sensorimotor mismatch, temporal sequence mismatch, and duration mismatch) enabling direct comparison of mismatched responses across animals.

### Large-scale, multi-modal population recordings

Previous datasets are typically limited to a single recording modality, preventing comparison of signals at different spatial and temporal scales. Our dataset combines Neuropixels electrophysiology (providing single-unit resolution across many brain regions simultaneously), two-photon mesoscope imaging (providing cell-type-specific calcium signals across VISp and VISlm, two visual areas in the mouse visual cortex), and SLAP2 imaging (providing subcellular dendritic recording in in the center of VISp). This multi-modal approach allows researchers to address questions about predictive processing at scales ranging from subcellular compartments to brain-wide networks.

## Experimental design

### Two cohorts design

To investigate whether prior experience with a specific predictive context influences neural responses to prediction violations, animals were divided into two cohorts that differed in their habituation experience and the order in which experimental sessions were presented. Both cohorts underwent all four mismatch session types, but the session experienced first (and for which animals had extensive prior habituation) differed between cohorts. This design enables within-animal comparison of mismatch responses across contexts, while the between-cohort comparison reveals how learned expectations from habituation shape these responses [@aizenbud2026neural].

- The **motor cohort** was habituated in a closed-loop visuomotor environment in which locomotion on a running disc controlled the phase of a vertical drifting visual grating stimulus that mimicked optic flow. During habituation (days 6–10, with session durations increasing from 8 to 48 min) and full-length training sessions (\>1 h), animals experienced continuous closed-loop optic flow without any mismatch events. Experimental sessions where neuronal activity was recorded were then conducted in the following fixed order:

  1.  Sensorimotor mismatch,

  2.  Standard oddball

  3.  Sequence mismatch

  4.  Duration mismatch.

- The **sequence cohort** was habituated to passively view repeating sequences of drifting gratings (A–B–C–D–grey) without any mismatch events. During habituation (days 6–10, durations 8–48 min) and full-length training sessions (\>1 h), animals viewed these sequences while freely running on the disc, which had no effect on the visual stimulus. Experimental sessions where neuronal activity was recorded were then conducted in the following fixed order:

  1.  Sequence mismatch

  2.  Duration mismatch

  3.  Standard oddball

  4.  Sensorimotor mismatch.

In both cohorts, the session that matched the habituation context was presented first, ensuring maximal learned expectation for the primary mismatch type. The remaining three sessions were presented in a counterbalanced order across cohorts. Each session was run in immediate succession: once for Neuropixels electrophysiology and twice for mesoscope two-photon calcium imaging, resulting in four or eight total recording sessions per animal. Given a limited throughput, experiments with the SLAP2 platform focused on the motor cohort. Each platform was used in a way that leverage their respective strengths: Experiments using the Mesoscope modality aimed to target the same exact population of neurons across all sessions types twice for a total of 8 cell-matched sessions; experiments using the Neuropixels modality were new probe insertions each day and aimed to record from the same areas (but not the same units) across all 4 types exactly once; experiments on the SLAP2 modality aimed to record the same neuron across all 4 sessions types exactly once. Across all modalities, those goals were met with pass/failure rates that are shared below. This cross-modality allocation is summarized in [Figure 1C](#fig-graphical-abstract). QC-passing unit yields across the four Neuropixels recording days are summarized in [Supplementary Figure 2](#fig-supp-neuropixels-unit-yield).

**Four predictive contexts**

The four distinct session contexts each targeted a different aspect of predictive processing. For all 4 contexts, the stimuli table containing both recurring and deviant trials were created at the onset of each session. The resulting tables were then subsequently shuffled so that the mouse could not predict the exact occurrence of deviants (pseudo-random). The order of stimuli blocks (deviant vs control blocks) were maintained across all sessions.

The shared within-session architecture and context-specific stimulus selection are summarized in [Figure 2](#fig-interactive-experimental-design).

:::{iframe} ./interactive/experimental-design.html
:label: fig-interactive-experimental-design
:width: 100%
:title: Predictive-processing stimulus viewer
:placeholder: ./images/figures/generated/figure-02-context-controls.svg

Within-session architecture for cross-context comparison. In the **Static** view,
**A** shows the common session sequence: a standard control precedes each context
block and is repeated immediately afterward, followed by shared randomized,
duration, open-loop, receptive-field, and zebra-movie blocks. **B** details the
four contexts and the control and system-identification stimuli used to measure
context-induced changes in response properties. The **Interactive** view
mirrors panel A: select one of the four contexts from the vertical selector above
the Context block or select any shared control or system-identification block
directly. It reconstructs
contiguous rows from the pinned generated stimulus tables in their source
pseudo-randomized order, with the source trial number shown for each frame.
The Movie block plays an excerpt of the canonical zebra stimulus, and receptive-field
mapping uses the stated 120° × 95° angular projection. Sources: pinned
[example tables](https://github.com/AllenNeuralDynamics/openscope-community-predictive-processing/tree/0365ae32f0f0473320ed202b7c5d2bce6cf5df6b/code/stimulus-control/src/Mindscope/examples),
[generator](https://github.com/AllenNeuralDynamics/openscope-community-predictive-processing/blob/0365ae32f0f0473320ed202b7c5d2bce6cf5df6b/code/stimulus-control/src/Mindscope/generate_experiment_csv.py),
[Bonsai workflow](https://github.com/AllenNeuralDynamics/openscope-community-predictive-processing/blob/0365ae32f0f0473320ed202b7c5d2bce6cf5df6b/code/stimulus-control/src/Mindscope/generic_oddball.bonsai),
and public NWB intervals for
[electrophysiology](https://dandiarchive.org/dandiset/001637/draft/files) and
[mesoscope](https://dandiarchive.org/dandiset/001768/draft/files).
:::

The mismatch repeat count and session length were informed by the five
published visual oddball paradigms compared in
[Supplementary Table 1](#table-supplementary-oddball-studies). Those studies
reported 10--144 required oddball repeats and total session durations ranging
from 6 min to 2 h. We therefore set each 26-min context block to 1.35 mismatch
events per minute for each of four deviant types (5.4/min combined), targeting
approximately 35 repeats per deviant type and 140 mismatch events per context
block. This placed per-deviant sampling within the published range while
keeping the complete shared block sequence to approximately 71 min and applying
the same event rate across all four predictive contexts.

#### Session type 1: Standard oddball.

Full-field sinusoidal drifting gratings were presented in a classical oddball paradigm. The standard stimulus (0° orientation, 0.04 cycles per degree, 2 Hz temporal frequency, 100% contrast) was presented with high probability, with each trial consisting of a 343 ms stimulus presentation followed by a 343 ms grey inter-stimulus interval (686 ms total trial duration). Deviant stimuli occurred randomly at a combined rate of 5.4 per minute (1.35/min per type) and included: orientation deviants at 45° and 90°, a halt deviant (temporal frequency set to 0, producing a stationary grating), and an omission deviant (contrast set to 0, producing a blank screen).

#### Session type 2 — Sensorimotor mismatch.

Optic flow was coupled to the animal's locomotion on the running disc, creating a closed-loop visuomotor environment. A full-field sinusoidal grating (0° orientation, 0.04 cpd) was displayed with its phase updated at 30 Hz based on wheel rotation. The coupling gain was set such that the visual flow was consistent with that experienced by a freely moving mouse. Mismatch events were introduced by transiently decoupling visual flow from locomotion for 343 ms. Mismatch types (each at 1.35/min) included: motor halt (temporal frequency set to 0, freezing grating motion despite continued locomotion), motor omission (contrast set to 0, removing the grating entirely), and motor orientation changes (grating orientation shifted to 45° or 90° while drifting at 2 Hz independent of the wheel). A minimum interval of 2 s separated consecutive mismatch events, with a 5 s buffer at the start and end of the block.

#### Session type 3 — Sequence mismatch.

Animals were presented with repeating five-element sequences of drifting gratings. Each sequence consisted of four oriented gratings (90°–45°–0°–45°) followed by a grey inter-sequence interval with each element presented for 250 ms, yielding a total sequence duration of 1.25 s. All gratings were full-field (0.04 cpd, 2 Hz temporal frequency, 100% contrast). Mismatch events were introduced by substituting the third element (normally 0°) of a sequence at a combined rate of 5.4 mismatch sequences per minute. Mismatch types included: orientation substitution to 45° (producing a repeated element where a change was expected), orientation substitution to 90° (introducing a novel orientation), halt (stationary grating), and omission (blank screen at the substitution position).

#### Session type 4 — Duration/temporal mismatch.

Full-field sinusoidal drifting gratings (0° orientation, 0.04 cpd, 2 Hz temporal frequency, 100% contrast) were presented with a standard trial structure of 343 ms stimulus followed by a 343 ms delay (686 ms total). Temporal prediction violations were introduced by altering the inter-stimulus delay while keeping the stimulus duration constant. Deviant delays included 150 ms (shorter than expected), 500 ms, and 1000 ms (longer than expected), each occurring at 1.35/min. Omission deviants (contrast = 0) were also included at 1.35/min.

### Shared session design

All four session types shared an identical set of control blocks presented before and after the main mismatch block, enabling cross-session normalization and quality assessment. Each session comprised the following blocks in order:

1.  Standard control block (6.4 min): 14 grating orientations (spaced every 22.5° from 0° to 315°) plus omission and halt trials, each repeated multiple times and presented in shuffled order. Each trial used the standard 343 ms stimulus + 343 ms delay structure (0.04 cpd, 2 Hz, 100% contrast, full-field). This block provides orientation tuning curves and adaptation-free baselines.

2.  Main mismatch block (26 min): The session-specific mismatch paradigm (standard oddball, sensorimotor, sequence, or duration mismatch, as described above).

3.  Standard control block (6.4 min): A repeat of the first control block, enabling assessment of response stability over the session.

4.  Sequential control block (4.7 min): The same 14 orientations plus omissions and halts as in the standard control block, but presented with 250 ms duration (matching the temporal structure of the sequence mismatch paradigm) and shuffled randomly without sequential structure. This serves as a non-sequential baseline for the sequence mismatch session.

5.  Jitter (duration) control block (6.4 min): Gratings (0° orientation, standard parameters) presented with seven different inter-stimulus delays (150, 343, 500, 750, 1000, 1500, and 914 ms), each repeated uniformly across the block, plus omission trials. This provides a matched-stimulus baseline for the duration mismatch session, where all delays occur with equal probability.

6.  Open-loop prerecorded block (6.4 min): A shared pre-recorded wheel-derived phase trajectories (sampled at 30 Hz from previous running sessions) drove the grating phase in open loop, replicating naturalistic visual flow patterns without actual closed-loop coupling. Motor mismatch events (orientation changes, halts, and omissions, each at 1.35/min) were injected into this playback, providing a sensorimotor mismatch control condition where the animal's locomotion does not match the visual flow.

7.  Natural movie block (10 min): A naturalistic "zebra noise" movie (120° × 95° visual field, 30 fps, 300 s duration, presented twice) was displayed [@skriabine2026zebra]. This stimulus serves as a shared reference for cross-session and cross-modality comparison, and provides a rich stimulus for characterizing neural response properties.

8.  Receptive field mapping block (5 min): A small drifting grating patch (20° diameter, 0.08 cpd, 4 Hz temporal frequency, 80% contrast) was presented at 81 positions on a 9 × 9 grid spanning ±40° of visual space in 10° steps. Three orientations (0°, 45°, 90°) were tested at each position with 5 repeats, using 250 ms presentations. This block enables estimation of spatial receptive fields for individual neurons.

## Multimodal recording hardware

:::{figure} ./images/figures/generated/multimodal-hardware.svg
:label: fig-multimodal-pipelines
:alt: Neuropixels, mesoscope, and SLAP2 rig geometry, mouse platforms, and brain-targeting strategies.
:width: 100%

Multimodal recording hardware. Rows compare Neuropixels electrophysiology, mesoscope two-photon calcium imaging, and SLAP2 dendritic imaging. Columns show each rig geometry, the corresponding head-fixed mouse platform, and the brain-targeting strategy. Neuropixels uses six acute trajectories spanning cortical and subcortical structures; mesoscope uses eight chronic imaging planes across VISp and VISlm; and SLAP2 samples proximal and apical dendritic compartments in a layer II/III pyramidal neuron. The figure is reconstructed from nine native-resolution images extracted directly from the editable PowerPoint source.
:::

# Methods

::::{dropdown} Show complete Methods
:class: manuscript-methods-dropdown

## Experimental animals

All animal procedures were approved by the Institutional Animal Care and Use Committee (IACUC) at the Allen Institute under protocol 2427 and conducted in accordance with NIH guidelines. Following surgery (see below), all mice were single-housed and maintained on a reverse 12-hour light cycle in a shared facility with room temperatures between 68º and 72ºF and humidity between 30 and 70%. All experiments were performed during the dark cycle. All mice in these experiments were given ad libitum access to food (regular or doxycycline diets) and water.

To systematically collect physiological data, we used standardized data collection and processing pipelines that were previously introduced [@devries2020survey; @groblewski2020headfixation; @durand2023acute; @bennett2024shield; @siegle2021survey]. The data collection workflow progressed from surgical headpost implantation and craniotomy to retinotopic mapping of cortical areas using intrinsic signal imaging, in vivo recording of neuronal activity using various modalities (Neuropixels, Mesoscope two photon imaging, SLAP2 dendritic two-photon imaging), brain fixation and brain histology (see [Figure 1](#fig-graphical-abstract)). We describe each one of those steps in the dedicated sections below. As part of this workflow, all mice were trained on one of two possible cohorts: A motor cohort and a sequence cohort. Details of each cohort is described in the behavioral training section below. Both behavioral cohorts were recorded with the Neuropixels and Mesoscope recording modality. Only the motor cohort was used for SLAP2 experiments. Each modality (Neuropixels, Mesoscope, SLAP2) was recorded with separate mice as they had different, modality-specific brain implants.

### Mesoscopic two-photon calcium imaging experimental animals

For experiments involving calcium imaging of GCaMP8s positive cells, male and female transgenic mice (n=14) with pan-neuronal cortical expression of GCaMP8s were used. Snap25-IRES-Cre [@harris2014anatomical] was bred in-house and crossed with a GCaMP8s reporter line (Oi4), both of which are maintained on a C57BL/6J background. Snap25-IRES-Cre;Oi4 breeding sets consisted of heterozygous Snap25-IRES-Cre mice (JAX stock \#023525) crossed with heterozygous or homozygous TIGRE2-RiboL1-jGCaMP8s-IRES-tTA2 (aka Oi4) mice (JAX stock #039267) [@daigle2018suite; @zhang2023gcamp]. Experimental animals were heterozygous for both transgenes (full genotype Snap25-IRES2-Cre/wt;Oi4(TIT2L-jGCaMP8s-RiboL1-WPRE-ICL-IRES-tTA2-WPRE)/wt). Experimental mice show pan-neuronal expression patterns of GCaMP8s in Snap25-expressing cell populations. All mice (including breeders) were maintained on a 200 mg/kg rodent doxycycline diet (Bio-Serv; Flemington, NJ) to suppress tTA2 activity (and subsequent TRE2 promoter-driven expression) during development. Breeding cages were continuously maintained on a doxycycline diet. At weaning (~p20) mice with correct genotype were transferred to cages with standard chow for the remainder of the experiment (PicoLab 5L0D; Lab Diet, Richmod, IN). Despite limiting GCaMP8s expression during development with doxycycline the mice exhibited a sex-dependent reduction in survival rates at older age; at p200 males had a 72% survival rate while females had a 61% rate, n=123). We were unable to identify a clear, single cause for this reduced survival rate.

### Neuropixels electrophysiology experimental animals

For experiments involving opto-tagging of inhibitory cells, male and female transgenic mice (n=17) expressing ChR2 in Cre-defined cell populations were used. Sst-IRES-Cre mice were bred in-house and crossed with an Ai32 channel rhodopsin reporter line, both maintained on a C57BL/6J background. Sst-IRES-Cre;Ai32 breeding sets consisted of heterozygous Sst-IRES-Cre mice (JAX stock \#028864) crossed with homozygous Ai32(RCL-ChR2(H134R)\_EYFP) mice (JAX stock #024109) [@madisen2012toolbox; @taniguchi2011resource]. Experimental mice were heterozygous for both transgenes (full genotype Sst-IRES-Cre/wt;Ai32(RCL-ChR2(H134R)\_EYFP)/wt). Cre+ cells from Ai32 lines are highly photosensitive, due to expression of Channelrhodopsin-2 [@zhang2006channelrhodopsin].

### SLAP2 experimental animals

For experiments involving simultaneous glutamate and calcium imaging, male and female wild-type C57BL/6J mice from JAX laboratory injected with Cre-dependent hSyn.FLEX.iGluSnFR4f.NGR and CAG.FLEX.RCaMP3 (or jRGECO1a) AAVs (serotype PHP.eB) were used. Sparse labeling was achieved via low titers (6E+8 vg/mL) of CaMKII-Cre virus. For experiments involving dendritic voltage imaging, male and female wild-type C57BL/6J mice from JAX laboratory injected with Cre dependent ASAP7 virus were used.

### Surgery & cranial window procedure: two-photon calcium imaging experiments

A subset of mice received a headpost and cranial window surgery as previously described [@groblewski2020headfixation; @devries2020survey]. Headpost and cranial window surgery was performed on healthy male and female transgenic mice (p54-p80) weighing no less than 14 grams at time of surgery. Pre-operative injections of dexamethasone (3-4.2 mg/kg, S.C.) and ceftriaxone (100-125 mg/kg, S.C.) were administered at 1h before surgery. Additionally, carprofen was administered for pain management (5-10 mg/kg, S.C.), and atropine was administered to suppress bronchial secretions and regulate heart rhythms (0.02-0.05 mg/kg, S.C.). Mice were initially anesthetized with 2-4% isoflurane and placed in a stereotaxic frame (Model# 1900, KOPF; Tujunga, CA), and isoflurane levels were maintained at 1.0-2.0% for surgery. An incision was made to remove skin, and the exposed skull was levelled with respect to pitch (bregma-lambda level), roll and yaw. The stereotax was zeroed at lambda using a custom headframe holder equipped with a stylus affixed to a clamp-plate. The stylus was then replaced with the headframe to center the headframe well at 2.8 mm lateral and 1.3 mm anterior to lambda. The headframe was affixed to the skull with white dental cement (C&B Metabond; Parkell; Edgewood, NY) and once dried, the mouse was placed in a custom clamp to position the skull at a rotated angle of 23° such that the visual cortex was horizontal to facilitate creation of the craniotomy. A circular piece of skull 5 mm in diameter was removed, and a durotomy was performed. A glass coverslip (cut from a single piece of glass to obtain a “stacked” appearance that consisted of a 5 mm diameter “core” and 7 mm diameter “flange”), was cemented in place with Vetbond (3M; St. Paul, MN). Dental cement was then applied around the cranial window inside the well to secure the glass window, and subsequently covered with black tempura paint to reduce glare during imaging. The mouse was given 1.0-1.5mL Lactated Ringers Solution (LRS) to help recover from the surgery and replace lost fluids. Post-surgical brain health was documented using a custom photo-documentation system and animals were assessed one, two, and seven days following surgery for overall health (bright, alert and responsive), cranial window clarity and brain health.

### Surgery & cranial window procedure: Neuropixels experiments

A subset of the mice received the SHIELD surgical procedure, which has previously been described [@bennett2024shield]. The SHIELD procedure was performed on healthy male and female transgenic mice (p53-p139) weighing no less than 14 grams at time of surgery. Pre-operative injections of dexamethasone (3-4.2 mg/kg, S.C.) and ceftriaxone (100-125 mg/kg, S.C.) were administered 1 h before surgery to reduce swelling and postoperative pain. Additionally, carprofen (5-10 mg/kg, S.C.) was administered for pain management, and atropine (0.02-0.05 mg/kg, S.C.) was administered to suppress bronchial secretions and regulate heart rhythms. Mice were initially anesthetized with 2-4% isoflurane and placed in a stereotaxic frame (Model# 1900, KOPF; Tujunga, CA). Isoflurane levels were maintained at 1.0-2.0%, and body temperature was maintained at 37.5°C for the duration of the surgery. An incision was made on the dorsal surface of the skull, and skin was removed in a teardrop shape, exposing the rostral rhinal vein between the eyes, the dorsal surface of the parietal and occipital skull plates, and stopping where the neck muscle begins to attach to the back of the skull. Next, the periosteum was removed from the skull surface to improve adhesion of the cement to the skull and prevent future scabbing and infection. Starting posterior of the left eye, angled forceps were used to separate cheek muscle from the skull, as well as connective tissue and muscle above the left ear. The cheek muscle was then pulled away from the skull and is stretched out so that it makes a seal with the left lateral portion of the well. The exposed skin (and any exposed soft tissue such as the cheek muscle) was then sealed with Vetbond, and the exposed skull was leveled with respect to pitch, roll, and yaw. Once the skull was leveled, bregma was identified using the custom bregma stylus. Without moving the stereotaxic arm in X or Y, the stylus was replaced with a custom “tracer” that provides a guide for marking the craniotomy with respect to bregma. A \#11 scalpel blade (or forceps) was used to etch a faint line in the skull around the tracer, which was then replaced with a shallow trench by lightly drilling without breaking through the skull (NeoBurr EF4). After etching was complete, the tracer was replaced with the headframe, which was then lowered in Z to make contact with the skull. Next, dental cement (C&B Metabond, Parkell) was used to attach the headframe to the skull. Once the cement hardened, the headframe was clamped into a custom frame, and the craniotomy and durotomy were performed. After sterilization, a custom implant was then lowered into the craniotomy. To provide a surface that can be glued to the skull, a flange on the implant extends beyond the cranial window and sits directly on the bone, where it was sealed with Vetbond and attached to the skull Once dry, the vetbond was covered with metabond to further secure the implant to the skull. The inner part of the implant sits on the brain surface. Any areas of exposed skull were then covered with cement. Any white cement on the inside of the well was coated with a layer of black tempura paint to reduce glare during ISI imaging. The mouse was given 1.0-1.5mL Lactated Ringers Solution (LRS) to help recover from the surgery and replace lost fluids. After removing the mouse from anesthesia, but prior to it waking up, a photo-documentation image was acquired. Finally, a removable plastic cap was placed over the well to protect the coated implant from cage debris, and the mouse was returned to its home cage for recovery. Over the following 7-14 days, mice were monitored regularly for overall health, cranial window clarity, and brain health.

### Surgery & cranial window procedure: SLAP2 experiments

A subset of mice received the SLAP2 Visual Cortex laser level procedure. The SLAP2 Visual Cortex laser level procedure was performed on healthy male and female transgenic mice (p53-p139) weighing no less than 14 grams at time of surgery. This is a variation on the Visual Cortex surgery used for the mesoscope experiments. To achieve single cell resolution the optimal angle for the SLAP2 microscope is as close to perpendicular to the craniotomy coverslip as possible. To facilitate this the headframe was attached after the coverslip was secured. This allowed the headframe to be installed on a consistent plane relative to the coverslip, ensuring proper interfacing between the craniotomy and SLAP2 microscope objective. Pre-operative injections of dexamethasone (3-4.2 mg/kg, S.C.) and ceftriaxone (100-125 mg/kg, S.C.) were administered 1 hour before surgery to reduce swelling and postoperative pain and protect against infection. Additionally, carprofen (5-10 mg/kg, S.C.) was administered for pain management, and atropine (0.02-0.05 mg/kg, S.C.) was administered to suppress bronchial secretions and regulate heart rhythms. Mice were initially anesthetized with 4% isoflurane and placed in a stereotaxic frame (Model# 1900, KOPF; Tujunga, CA). Isoflurane levels were maintained at 1.0-2.0%, and body temperature was maintained at 37.5°C for the duration of the surgery. An incision was made on the dorsal surface of the skull. Skin was removed in a teardrop shape; exposing the rostral rhinal vein between the eyes, the dorsal surface of the parietal and occipital skull plates and stopping where the neck muscle begins to attach to the back of the skull. Next, the periosteum was removed from the skull surface to improve adhesion of the cement to the skull and prevent future scabbing and infection. Starting posterior to the left eye, angled forceps were used to separate cheek muscle from the skull, as well as connective tissue and muscle above the left ear. The cheek muscle was then pulled away from the skull and stretched out so that it makes a seal with the left lateral portion of the well. The exposed skin, and any exposed soft tissue such as the cheek muscle, was sealed with Vetbond (3M; St. Paul, MN). The 5mm craniotomy “tracer” provided a guide for marking the craniotomy and was centered at 2.8 mm lateral and 1.3 mm anterior to lambda. Forceps were used to etch a faint line in the skull around the tracer. Using the drill (NeoBurr EF4), without breaking through the skull, the etch was then replaced by a shallow trench. The mouse was rotated clockwise approximately 23 degrees to create a level surface to drill on and help angle the coverslip to accurately interface perpendicularly with the SLAP2 microscope. A well was created with a silicone polymer (Body Double Fast; Smooth-On; East Texas, PA) large enough to encompass the craniotomy and bregma. Craniotomy and durotomy were then performed. The mouse was rotated back 23 degrees counterclockwise for virus injection. A Nanoject III (Drummond; Broomall, PA) was then zeroed at bregma, and virus was injected with a beveled pipette at 3.1 mm lateral, 3.1 mm posterior to and at 3.1 mm lateral, 3.9 mm posterior to bregma, at depths of 0.3 mm and 0.6 mm below surface of the cortex for each point. The mouse was rotated back clockwise approximately 23 degrees to return the craniotomy to an approximately leveled plane relative to pitch, roll, and yaw. A glass coverslip (cut from a single piece of glass to obtain a “stacked” appearance that consisted of a 5 mm diameter “core” and 7 mm diameter “flange”), was lowered into the craniotomy. The 2mm flange was cemented in place with Vetbond. A custom in-house laser leveling tool was used to level the coverslip so that it was perpendicular to the stereotaxic arm. The mouse skull was turned back 23 degrees counterclockwise, and pitch was raised 6 degrees to keep the coverslip in a parallel plane relative to the headframe. This allowed for proper interfacing of the glass coverslip and the SLAP2 microscope when the mouse was head fixed in the headframe. Using the stereotaxic arm, a headframe was lowered onto the skull and secured in place with clear dental cement (C&B Metabond; Parkell; Edgewood, NY), covering all remaining exposed skull. Black tempura paint was applied on top of the clear cement outside the headframe to reduce light leaks. The mouse was given 1.0-1.5mL Lactated Ringers Solution (LRS) to help recover from the surgery and replace lost fluids. After removing the mouse from anesthesia, prior to it waking up, post-surgical brain health was documented using a custom photo-documentation system. Animals were assessed on days one, two, and seven following surgeries for overall health (bright, alert and responsive), cranial window clarity and brain health.

## Intrinsic signal imaging / retinotopic mapping

Intrinsic signal imaging (ISI) measures the hemodynamic response of the cortex to visual stimulation across the full field of view. This retinotopic mapping represents the spatial relationship between the visual field and cortical locations within each visual area. For both Neuropixels and Mesoscope two-photon imaging experiments, retinotopic maps were used to delineate functionally defined visual area boundaries and to guide targeting of in vivo two-photon calcium imaging to retinotopically defined locations in primary and secondary visual areas.

### Animal preparation

For every ISI imaging session, mice were lightly anesthetized with 1–1.4% isoflurane delivered via a SomnoSuite system (model 715; Kent Scientific, CT, USA) at a flow rate of 100 mL/min, supplemented with ~95% O₂ (Pureline OC4000; Scivena Scientific, OR, USA). Lubricating eye ointment (Lacri-Lube; Refresh) was applied to maintain corneal hydration and clarity during anesthesia. Mice were positioned on a lab jack and head-fixed such that the cranial window was normal to the imaging axis. The head frame and clamping mechanism ensured consistent positioning of the eye relative to the stimulus monitor across experiments.

### Image acquisition system

To map retinotopic organization and standardize data acquisition, a custom ISI system coupled to visual stimulation was used. The cortical surface was illuminated with a ring of independently controlled LEDs, including green (peak λ = 527 nm, FWHM = 50 nm; Cree Inc., C503B-GCN-CY0C0791) and red (peak λ = 635 nm, FWHM = 20 nm; Avago Technologies, HLMP-EG08-Y2000) wavelengths mounted on the objective. A tandem lens configuration (Nikon Nikkor 105 mm f/2.8 rear lens and Nikon Nikkor 35 mm f/1.4 front lens) provided 3.0× magnification (M = 105/35). The back focal plane of the front lens was positioned adjacent and coplanar to the cranial window (working distance: 46.5 mm). A bandpass filter (Semrock FF01-630/92 nm) was used to preferentially transmit longer-wavelength reflectance signals while minimizing contamination from the stimulus monitor and ambient light.

Image acquisition and illumination were controlled via custom Python software. Images were acquired using an Andor Zyla 5.5 10-tap sCMOS camera at 40 Hz, with frame timing governed by the camera’s 40 MHz hardware clock. Image acquisition and stimulus presentation were synchronized via hardware triggering from a National Instruments digital I/O board. Raw images (2560 × 2160 pixels, 16-bit) were spatially (4×4) and temporally (4×) binned to yield 640 × 640 pixel frames at 10 Hz with 32-bit dynamic range and an effective pixel size of 10 µm.

### Intrinsic imaging visual stimulus

The lambda–bregma axis of the skull was oriented at a 30° pitch relative to horizontal, corresponding to an eye position approximately 60° lateral to the midline and 20° above the horizon [@oommen2008eye]. A 24″ monitor was positioned 10 cm from the right eye to maximize visual field coverage. The monitor was rotated 30° relative to the dorsoventral  axis and tilted 70° relative to the horizon to maintain perpendicularity to the optic axis.

The visual stimulus consisted of a drifting bar containing a contrast-reversing checkerboard pattern on a gray background. The bar swept across the four cardinal directions at 0.1 Hz, with 10 repetitions per direction [@kalatsky2003intrinsic]. The bar measured 20° × 155°, with individual checker squares of 25°. Stimuli were spatially warped to approximate a spherical visual field projection on a flat display [@marshel2011specialization].

### Image acquisition and processing

A high-resolution image of the cortical vasculature was first acquired under green illumination to serve as a fiducial reference. The imaging plane was then defocused 500–1500 µm below the surface to capture intrinsic signals. Up to 10 ISI time series were collected per experiment.

Time series were preprocessed by removing the time-averaged pixel intensity (DC component) to improve signal-to-noise ratio. A discrete Fourier transform (DFT) was computed at the stimulus frequency. Phase maps were generated from the phase angle of the DFT and used to map visual field position onto cortical coordinates. Sign maps were derived by computing the sine of the angle between the gradients of the altitude and azimuth phase maps. Final sign maps were averaged across at least three time series (minimum of 30 sweeps per direction).

### Automated sign map segmentation and annotation

For each experiment, visual field sign maps were segmented into distinct visual areas using an automated algorithm (adapted from [@garrett2014topography]). Segmentation was based on three criteria: (1) each area contains a uniform visual field sign, (2) each area represents a unique (non-redundant) portion of visual space, and (3) adjacent areas with the same sign exhibit redundant visual field representations.

### Eccentricity and target map generation

Eccentricity maps were computed relative to the center of visual space (0° azimuth, 0° altitude). When the eye is properly aligned, this point corresponds approximately to the anatomical center of V1. The eccentricity at the V1 centroid was used as a quality control metric to identify experiments with significant eye misalignment (\>15°).

To define target regions for two-photon imaging, eccentricity maps were thresholded to include locations within 10° of the V1 center. These targeting maps were overlaid onto vasculature images to provide fiducial landmarks for aligning imaging fields across sessions and ensuring retinotopic consistency.

### ISI quality control

Quality control of ISI-derived maps consisted of four steps:

1.  Brain surface and vasculature images were inspected before and after acquisition for clarity, focus, and cranial window positioning.

2.  Individual trials were evaluated for sufficient visual coverage, continuity of phase maps, localization of amplitude maps, and expected sign map organization. Only trials meeting these criteria were included (minimum of three trials).

3.  Automated segmentation was required to identify at least six visual areas (VISp, VISlm, VISrl, VISal, VISam, VISpm).

4.  Final maps were assessed for visual field coverage (35–60° altitude, 60–100° azimuth), minimal bias (\<10° range imbalance), alignment of the retinotopic center with the V1 centroid, and minimum V1 area (\>2.8 mm²).

## Behavioral training

Mice were trained in individual sound-attenuating enclosures arranged in clusters. Each enclosure was arranged similarly to that of the mesoscope two-photon microscope, SLAP2 two-photon imaging microscope and the Neuropixels rigs. A 24” LCD monitor was positioned 15 cm from the mouse’s right eye, with the sagittal axis of the head parallel to the screen. A registered headframe clamp was attached to a behavior stage equipped with kinematic mounts to ensure repeatable placement of the stage in the enclosure. Each stage consisted of a fixed-position headframe clamp and adjustable running wheel. Enclosures were equipped with a camera coupled with IR illumination to monitor mouse activity. Those videos were recorded but kept temporarily on disk.

Animals received a 2-week training procedure following a previously published head-fixation habituation protocol [@devries2020survey].

Habituation to handling and head-fixation was performed for five days: On days 1-2 mice were removed from the home cage and gently handled for 1-2 min. On days 3-5 mice were removed from the home cage and handled for 1-2 min, then head-fixed by securing the headframe in the behavior stage clamping mechanism. The stage was then placed in the lit behavior enclosure for 5-10 min.

Passive behavior training was then performed to habituate mice to extended periods of head-fixation and expose the mice to visual stimuli. On days 6-10 mice were removed from the home cage and handled for 1-2 min. Mice were then head-fixed to the behavior stage and the stage was placed in the behavior enclosure. A set of full-screen stimuli was displayed for increasing periods. Visual stimuli were displayed for increasing durations of 8, 18, 28, 38, and 48 min on days 6 through 10, respectively.

The habituation protocol included two cohorts of mice. (1) The **sequence cohort** passively viewed a repeating sequence of four drifting gratings (90°–45°–0°–45°) followed by a grey inter-sequence interval, without any mismatch events. Each element was presented for 250 ms, and gratings were full-field (0.04 cpd, 2 Hz temporal frequency, 100% contrast). Animals were free to walk and rotate the disc beneath their body; however, disc rotation had no effect on the stimuli presented on the screen. This established a learned expectation for the sequential structure. (2) The **motor cohort** was habituated in a closed-loop paradigm in which locomotion on the running disc controlled the phase of a full-field sinusoidal grating (0° orientation, 0.04 cpd) via a rotary encoder. This configuration approximated natural visual flow, such that forward locomotion produced corresponding backward grating motion consistent with that experienced by a freely moving mouse. No mismatch events were presented during any habituation sessions in either cohort. The full-length habituation sessions additionally included control blocks (standard control, sequential control, jitter control, open-loop prerecorded, natural movie, and receptive field mapping) identical to those used in the experimental sessions, further habituating the animals to the full session structure.

## Visual stimulation

All visual stimuli were generated using BonVision [@lopes2021bonvision], an open-source visual environment package running within the Bonsai reactive programming framework [@lopes2015bonsai]. For behavior training, Neuropixels recordings and mesoscope imaging, stimuli were rendered at 60 Hz and displayed on a gamma-calibrated ASUS PA248Q LCD monitor (1920 × 1200 pixels, 55.7 cm wide, 60 Hz refresh rate) positioned 15 cm from the animal's right eye (see [Figure 1](#fig-graphical-abstract)). A spherical warping correction (BonVision SphereMapping) was applied to all stimuli to compensate for the close viewing distance and flat display geometry, ensuring that apparent size, speed, and spatial frequency were constant across the visual field as seen from the mouse's perspective. The monitor subtended 120° × 95° of visual space. Mean luminance was 50 cd/m². Stimulus timing was synchronized to neural recordings via a photodiode placed on a sync square region of the monitor that alternated between black and white every 60 frames, and via digital synchronization pulses sent to a National Instruments digital board. The full stimulus code, Bonsai workflow, and parameter files are available on the project's GitHub repository ([https://github.com/AllenNeuralDynamics/openscope-community-predictive-processing](https://github.com/AllenNeuralDynamics/openscope-community-predictive-processing)). For SLAP2 recordings, the stimulation screen was smaller to account for physical constraints of the SLAP2 rig. <span class="manuscript-wip-inline"><strong>Work in progress:</strong> verify and add the SLAP2 display model, pixel dimensions, physical size, and visual-angle coverage.</span>

For each session, a stimulus table (CSV file) was generated programmatically by a Python script (generate_experiment_csv.py) using a session-specific random seed derived from the session UUID and timestamp, ensuring unique trial sequences across sessions while maintaining reproducibility. This CSV table specified all trial parameters (orientation, spatial frequency, temporal frequency, contrast, duration, delay, position, phase, trial type, and block membership) and was read by the Bonsai workflow (generic_oddball.bonsai) to drive stimulus presentation in sequence.

:::{note} Stimulus table and presentation sources
Pinned generated example tables are available for
[standard oddball](https://github.com/AllenNeuralDynamics/openscope-community-predictive-processing/blob/0365ae32f0f0473320ed202b7c5d2bce6cf5df6b/code/stimulus-control/src/Mindscope/examples/visual_mismatch_example.csv),
[sensorimotor mismatch](https://github.com/AllenNeuralDynamics/openscope-community-predictive-processing/blob/0365ae32f0f0473320ed202b7c5d2bce6cf5df6b/code/stimulus-control/src/Mindscope/examples/sensorimotor_mismatch_example.csv),
[sequence mismatch](https://github.com/AllenNeuralDynamics/openscope-community-predictive-processing/blob/0365ae32f0f0473320ed202b7c5d2bce6cf5df6b/code/stimulus-control/src/Mindscope/examples/sequence_mismatch_example.csv), and
[duration mismatch](https://github.com/AllenNeuralDynamics/openscope-community-predictive-processing/blob/0365ae32f0f0473320ed202b7c5d2bce6cf5df6b/code/stimulus-control/src/Mindscope/examples/duration_mismatch_example.csv),
together with the [table generator](https://github.com/AllenNeuralDynamics/openscope-community-predictive-processing/blob/0365ae32f0f0473320ed202b7c5d2bce6cf5df6b/code/stimulus-control/src/Mindscope/generate_experiment_csv.py)
 and [Bonsai presentation workflow](https://github.com/AllenNeuralDynamics/openscope-community-predictive-processing/blob/0365ae32f0f0473320ed202b7c5d2bce6cf5df6b/code/stimulus-control/src/Mindscope/generic_oddball.bonsai).
Exact synchronized tables for recorded sessions are stored as NWB `TimeIntervals`
in the public [electrophysiology](https://dandiarchive.org/dandiset/001637/draft/files)
and [mesoscope](https://dandiarchive.org/dandiset/001768/draft/files) Dandisets.
The example CSVs define the protocol and schema; they are not a replay of a
particular recorded session.
:::

In the sensorimotor mismatch context, the phase of the drifting grating was coupled to the angular position of the running disc via a rotary encoder. The wheel-to-visual coupling was computed as: phase (radians) = 2π × R × θ / tan(1/f × π/180), where R is the wheel radius-to-screen ratio (0.36), θ is the wheel angle in degrees, and f is the spatial frequency (0.04 cpd). This coupling was calibrated so that the resulting visual flow approximated the optic flow a freely moving mouse would experience during forward locomotion.

## Stimuli parameters

All drifting grating stimuli shared the following base parameters unless otherwise specified: spatial frequency 0.04 cpd, temporal frequency 2 Hz, 100% contrast, sinusoidal luminance profile, full-field extent (360° diameter with spherical correction). For the standard oddball, sequence mismatch, and duration mismatch sessions, gratings drifted at a fixed temporal frequency of 2 Hz. For the sensorimotor mismatch session, the grating phase was updated at 30 Hz (every other video frame) based on wheel rotation, with temporal frequency set to 0 in the stimulus table (wheel-controlled mode). Oddball/mismatch events occurred at a rate of 1.35 per minute per deviant type (5.4/min total across four deviant types) in all session types. The stimulus parameters for each session type and shared control blocks are detailed in the Experimental design section above.

## Neuronal recording modalities

### Neuropixels extracellular electrophysiology.

#### Habituation to the Neuropixels rigs.

Prior to the first recording, mice were habituated to the Neuropixels rigs every day for a week. These sessions were similar to the recording session in length but did not include oddballs. There were 2 cohorts of mice, one exposed to motor stimuli and the other to the sequence stimuli (see stimuli description).

#### Implant design for recordings

The implant was designed as stated in the surgery section and was described previously [@bennett2024shield]. Briefly, we created a CAD file with holes strategically placed above the areas of interest for our study (see [Supplementary Figure 1](#fig-supp-neuropixels-implant-trajectories)). Some hole coordinates have been previously validated to allow targeting of areas such as the center of VISp, and other hole coordinates were derived from publications, such as VISa [@lyamzin2019parietal]. Hole positions were adjusted using Pinpoint [@birman2023pinpoint]. Note that the placement of the implant on the brain can vary slightly due to mouse-to-mouse variability and surgical precision. The coordinates of holes were referenced from bregma; their diameters and intended target areas are represented in [Supplementary Figure 1](#fig-supp-neuropixels-implant-trajectories).

#### SORTA-Clear plug removal and agarose application

To prepare the brain for recording, the SORTA-Clear coating over the implant is removed and replaced with a temporary layer of Kwik-Cast (World Precision Instruments). The mouse is anesthetized with isoflurane (5% induction, 1-2% maintenance, 100% O2) and eyes protected with ocular lubricant (I-DROP, VetPLUS). Body temperature is maintained at 37.5°C (TC-1000 temperature controller, CWE, Incorporated). The well is cleaned of any debris using ethanol swabs. Then, the inside of the well surrounding the SORTA-Clear plug is painted with white Metabond to improve visibility during probe insertion. Once the Metabond is dry, the well is flooded with enough ACSF to completely submerge the SORTA-Clear sheet, which is then removed with small forceps, starting at the anterior or posterior end of the sheet and peeling gently to remove it in one piece. Once the SORTA-Clear sheet is completely detached from the implant, the edges of implant holes are tested with small forceps to ensure all holes are free of SORTA-clear or debris. ACSF is removed from the well using Sugi spears (Kettenbach) and the well is filled with Kwik-Cast. Once the Kwik-Cast is fully dry, a plastic protective cap is secured on the well to protect against debris and the mice are returned to their home cage. This preparation is generally performed Fridays for recordings on Mondays to avoid using isoflurane on the day of experiment.

#### Head fixation.

On the day of recording, the mouse is removed from its home cage and clamped to the running wheel on the experimental rig. Wheel height is adjusted as needed for each mouse. Once head-fixed, the protective well cap and Kwik-Cast layer are removed. The ground wire is tucked into the side of the well and any excess debris cleaned using a Sugi spear or cotton tipped applicator. Approximately 0.2ml of agarose (4%: 0.4 g of BioRad Low Melt and 0.4 g of Sigma agarose high electroendosmosis in 20.2 ml ACSF [@durand2023acute] is applied in a smooth layer over the entire implant surface and ground wire. After popping any large bubbles, the agarose is allowed to set for ∼10 seconds. To prevent the agarose from drying out during the experiment, a layer of silicon oil is applied over exposed agarose with a toothpick. At the end of the experiment, the agar is removed and replaced with Kwik-Cast.

The 3D-printed protective cone was then lowered to prevent the mouse’s tail from striking the probes. An infrared dichroic mirror was placed in front of the right eye to allow the eye-tracking camera to operate without interference from the visual stimulus.

#### Grounding.

A 32 AWG silver wire (A-M Systems) is epoxied to the headframe during the implant surgery and served as the ground connection. The wire is pre-soldered to a gold pin embedded in the headframe well, which mates with a second gold pin on the protective cone. This second gold pin is connected to both the behavior stage and the probe ground. Prior to the experiment, the brain-to-probe ground path is checked using a multimeter. The reference connection on the Neuropixels probes is permanently soldered to ground using a silver wire, and all recordings are made using the tip reference configuration. The headstage grounds (which are contiguous with the Neuropixels probe grounds) are connected with 36 AWG copper wire (Phoenix Wire). All probes are connected in parallel to animal ground.

#### Neuropixels probes

All neural recordings were carried out with Neuropixels 1.0 probes [@jun2017neuropixels], as previously described [@siegle2021survey; @durand2023acute]. The 384 electrodes closest to the tip are used, providing a maximum of 3.84 mm of tissue coverage. The signals from each recording site are split in hardware into a spike band (30 kHz sampling rate, 500 Hz highpass filter) and a [Local Field Potential](https://www.sciencedirect.com/topics/neuroscience/local-field-potential) (LFP) band (2.5 kHz sampling rate, 1000 Hz lowpass filter). Our goal was to insert six probes into the same mouse’s brain on each of 4 consecutive days. To distinguish the paths of these different penetrations, we use two dyes, CM-DiI (1 mM in ethanol; ThermoFisher Product \#V22888) on day 1 and 2 and CM-DiD (1mM in ethanol; AAT Bioquest catalogue number 22060) on day 3 and 4. The probes are coated with dye before recordings by immersing them at least 3mm into a well filled with dye. Each probe are dipped five times to ensure adequate coating.

#### Neuropixels probe insertion

Our custom experimental rig can insert up to six Neuropixels probes simultaneously (see [Figure 3](#fig-multimodal-pipelines)). Each probe is mounted on a separate 3-axis micromanipulator with a 15 mm travel range (New Scale Technologies, Victor, NY). Probes are driven to their target holes and lowered to the surface of the brain while the experimentalist monitores a camera feed to avoid vasculature and watches real-time signals on the OpenEphys GUI to identify activity indicative of the brain surface. If the probe need adjustment when attempting to insert (e.g. to avoid vessels), the probe are completely retracted out of the silicon oil to prevent probe bending. Once all probes reach the brain surface, each probe is zeroed and set to insert 3100 μm deep at 200 μm/min and then retracted 100 μm to their final depths to reduce tissue compression and subsequent electrode zdrift relative to the brain. Once all probes reach their final depth, the probes are allowed to settle for ∼30 minutes, and a photo documentation of the inserted probes is captured. Sometimes a probe can not be inserted into its assigned hole, failures are generally due to dura regrowth. Overall, we achieved a penetration success of 5.8 probes per session.

#### Data acquisition and synchronization.

Neuropixels data is acquired at 30 kHz (spike band) and 2.5 kHz (LFP band) using the Open Ephys GUI [@siegle2017openephys]. Gain settings of 500× and 250× are used for the spike band and LFP band, respectively. Probes are connected to a PXIe card inside a National Instruments chassis.

Videos of the eye, body and face are acquired at 60 Hz. The angular velocity of the running wheel is recorded at the time of each stimulus frame, at approximately 60 Hz. Synchronization signals for each frame are acquired by a dedicated computer with a National Instruments card acquiring digital inputs at 100 kHz, which is considered the master clock. A 32-bit digital ‘barcode’ is sent with an Arduino Uno (SparkFun DEV-11021) every 30 s to synchronize all devices with the neural data. Each Neuropixels probe has an independent sample rate between 29,999.90 Hz and 30,000.31 Hz, making it necessary to align the samples offline to achieve precise synchronization. The synchronization procedure uses the first matching barcode between each probe and the master clock to determine the clock offset, and the last matching barcode to determine the clock scaling factor.

To synchronize the visual stimulus to the master clock, a silicon photodiode (PDA36A, Thorlabs) was placed on the stimulus monitor above a “sync square” that alternated between black and white every 60 frames.

#### Stimulus Monitor

We lower a black curtain over the front of the rig, placing the mouse in complete darkness except for the visual stimulus monitor. Visual stimuli are generated using custom scripts based on PsychoPy<sup>9</sup> and are displayed using an ASUS PA248Q LCD monitor, with 1,920 × 1,200 pixels (55.7 cm wide, 60 Hz refresh rate). Stimuli are presented monocularly, and the monitor is positioned 15 cm from the right eye of the mouse and spans 120° × 95° of visual space before stimulus warping. Each monitor is gamma corrected and has a mean luminance of 50 cd m<sup>−2</sup>. To account for the close viewing angle of the mouse, a spherical warping is applied to all stimuli to ensure that the apparent size, speed and spatial frequency were constant across the monitor as seen from the mouse’s perspective.

#### Probe removal and cleaning

After each experiment, the probes are retracted from the brain at a rate of ~3000*μ*m/min and the mouse is removed from head fixation and returned to its home cage. If another recording session is to occur the same day, the probes are then immersed in a well of freshly made 1% Tergazyme mixed with agarose for 5 minutes to remove excess residue, followed by immersion in 1% Tergazyme for 30 minutes, immersion in Milli-Q water for 25 minutes, and dipped in 100% isopropyl alcohol for 1 minute. After the last recording session of the day, the probes are immersed in a well of freshly made 1% Tergazyme for ~12 hours.

#### Quality Control for Neuropixels recording sessions

Possible QC failure can come from these cases: white foam buildup on the edge of the eye covering the pupil, software failures compromising critical data streams, visual stimulus synchronizing failure, cortical bleeding or compromised brain health resulting in low unit activity and/or atypical visual responses, gap in data acquisition and discovery of purulent material over right hemisphere during ex-vivo imaging. Out of a total of 56 sessions, 12 are excluded for eye foam.

#### Optotagging protocol

At the end of every experiment, an optotagging protocol is run during which the cortical surface is stimulated with blue light. In Sst-IRES-Cre/wt;Ai32(RCL-ChR2(H134R)\_EYFP)/wt mice, this protocol allowes us to identify putative Sst+ cortical interneurons by an increase in spiking activity time-locked to laser stimulation (and consequent ChR2 activation). Blue light is delivered by a 473 nm laser (Laser Quantum, model Ciel or Cobolt model 06-MLD). The light source is coupled to a 400 μm diameter fiber optic cable (Thorlabs) or bifurcated fiber bundle (Thorlabs, BFYL4LF01), with the tip(s) positioned such that blue light illuminates the entire cranial window. Two types of stimuli at 3 different light levels are randomly interleaved: a 10 ms pulse, and a 1s raised cosine ramp. For the pulse stimulus, a 0.5 ms ramp is applied at the beginning and end of the pulse. Stimuli are presented at intervals of 1.5 s plus a uniformly distributed delay between 0 and 0.5 s. Representative laser-aligned responses and session-level yield summaries are shown in [Supplementary Figure 5](#fig-supp-optotagging-heatmaps).

#### Clearing with life canvas

We use published protocols to perform the tissue sample preparation steps for clearing a whole mouse brain. Briefly, the brain is perfused and fixed in 4% paraformaldehyde in order to prepare it for light sheet microscopy. In a timeline of two weeks, the brain will be stripped of lipids [@myers2023delipidation] and rendered transparent in an index matching solution [@myers2023indexmatching], allowing for viewing the morphology of anatomical brain structures. Then the brain is embedded in agarose for imaging [@myers2023embedding]. This protocol collection is ideal for experiments where high quality clearing is desired for imaging finer cell structures that are located deep in the brain, or when it is necessary to preserve endogenous fluorescence.

#### Imaging of cleared brains for Neuropixels probe trajectory

Agarose blocks containing cleared mouse brains were fixed to the sample arm of a light sheet microscope (LifeCanvas Technologies) and submerged into an immersion oil bath matching the refractive index for the clearing technique described above (Cargille Laboratories). Specimens were oriented such that the light sheet and focal plane aligned to the transverse anatomical plane with the superior surface closest to the imaging objective and the excitation light entering from either the left or right hemisphere, determined relative to the sagittal mid-plane. Data was collected using a 4X 0.20 NA objective, modified to 3.6X for oil immersion, stepped axially to produce voxels 2.0 x 1.8 x 1.8 𝞵m^3 in (z, y, x).

Raw data was then packaged with relevant metadata, uploaded to cloud storage, and used to create derived data, including contiguous image volumes for each channel, transform fields mapping to/from the Allen CCFv3, and neuroglancer viewer links for visualizing results.

### Two-photon mesoscope calcium imaging

Multi-plane calcium imaging was performed using a dual-beam mesoscope (Multiscope), enabling simultaneous imaging of two planes and effectively doubling imaging throughput (Orlova, Tsyboulski, Najafi et al., 2020). The system builds on the 2P-RAM platform (Sofroniew et al., 2016) with a compact optomechanical add-on that introduces a second excitation beam and simplifies alignment.

The dual-beam configuration consists of: (1) a delay line to split the excitation beam and temporally offset one beam by half the laser pulse period; (2) a secondary z-scanner to independently position each beam along the axial (z) dimension; and (3) a custom demultiplexing unit. Temporal encoding of the excitation beams enables separation of fluorescence signals based on photon arrival time at the detector. Laser excitation was provided by a Coherent Axon laser operating at 910 nm.

The system was controlled using customized ScanImage software (Vidrio Technologies) in conjunction with an in-house workflow sequencing engine (WSE; see below). Emitted fluorescence was detected with a single photomultiplier tube (PMT), and signals from the two imaging planes were separated using a custom analog demultiplexing circuit (Orlova et al., 2020). Demultiplexing was achieved by multiplying the PMT signal with two complementary square waveforms corresponding to the temporal windows of each excitation beam.

The integration window (6.25 ns; half the laser pulse period) does not fully capture the fluorescence decay, resulting in partial signal bleed-through between channels (~10% inter-plane crosstalk). This residual crosstalk was reduced using an independent component analysis (ICA)-based demixing algorithm (see below). National Instruments data acquisition hardware (PXI chassis, PXIe-6363 boards) was used for system control and data acquisition.

To coordinate hardware and software components, a workflow sequencing engine (WSE) was developed in Python. The WSE uses a distributed messaging interface to communicate with ScanImage, the stimulus presentation computer, synchronization hardware, and behavioral monitoring systems (body and eye tracking). The WSE also integrates user-guided steps: when manual intervention is required (e.g., hardware adjustments), the system prompts the operator and records task completion. Upon completion of each experiment, the WSE aggregates all data streams and automatically initiates transfer to a centralized data repository.

#### Habituation to Mesoscope rig

Prior to the first imaging session, mice were habituated to the imaging rig under head fixation for 30 minutes. Habituation sessions were conducted under the same ambient conditions as experimental recordings (dim red light, imaging environment) but without visual stimulus presentation. These sessions allowed animals to acclimate to head fixation, the rotating disk, and the experimental setup prior to data collection.

During habituation, the mesoscope objective was aligned to be as close as possible to perpendicular to the cranial window to optimize imaging quality. Alignment was verified using an infrared (IR) viewer by directing the excitation beam onto the cranial window and confirming that the reflected signal returned to the objective. Stage coordinates (X, Y, R1 & R2 - objective rotation) were recorded to facilitate consistent field-of-view positioning and cell matching across subsequent imaging sessions.

#### Mesoscope imaging data collection

All experimental setup was performed under dim red illumination to preserve the reversed light–dark cycle; imaging was conducted in darkness. Mice were head-fixed on a freely rotating disk, allowing voluntary locomotion. During imaging, the mouse eye was positioned 15 cm from the display. The screen center was located 118.6 mm lateral, 86.2 mm anterior, and 31.6 mm dorsal relative to the right eye, aligning the display normal to the average gaze axis.

The disk surface was covered with removable foam (Super-Resilient Foam, McMaster) to reduce motion-related artifacts. Water-based ultrasonic gel was used as the immersion medium to minimize evaporation and leakage during imaging.

On the first imaging day, ISI-derived targeting maps generated for each animal were used to identify regions of interest (ROIs) in VISp and VISl. Target locations were verified by registering the ISI-derived targeting map, overlaid on a reference image of the cortical surface vasculature, to live epifluorescence images acquired under blue light illumination. Alignment was performed using superficial vascular landmarks (e.g., vessel branching patterns and intersections) across the 5 mm cranial window, enabling accurate localization of regions of interest and consistent targeting across imaging sessions.

Following this alignment, the cranial window was visualized under two-photon (2P) imaging. The live 2P surface image was compared to the ISI-targeting map and vasculature reference to define ROIs for each recording site (400 × 400 µm field of view; 512 × 512 pixels). For each ROI, a 2P reference image of the cortical surface was acquired.

Imaging planes were then positioned relative to the cortical surface at depths corresponding to cortical layers I (~0–100 µm), II/III (~100–300 µm), IV (~300–400 µm), and V (~400–500 µm), with exact depths adjusted based on cortical landmarks and image features. A reference image was acquired at each imaging plane to support subsequent field-of-view alignment and subsequent session cell matching.

After acquisition of reference images at the cortical surface and imaging depths, a z-stack centered on the imaging plane (±30 µm, 0.75 µm step size) was collected to assess cortical structure and estimate axial motion (see Quality Control, Z-axis stability). At the end of the first recording session, a widefield epifluorescence image of the cranial window is also acquired. This image is used for aligning and targeting the same field of views for successive imaging sessions.

For subsequent imaging sessions, previously defined imaging fields were re-identified using a stepwise alignment procedure to reproduce the field of view and imaging depth established during the initial imaging session.

1.  The mesoscope objective was first returned to the reference tilt (R1 and R2) and stage coordinates (x and y) established during habituation, providing an initial estimate of the imaging location.

2.  A live epifluorescence image of the cranial window was acquired and aligned to the reference epifluorescence image from the initial imaging session using superficial vascular landmarks to recover the targeted cortical regions.

3.  A two-photon image of the cortical surface was then acquired and matched to the corresponding surface reference image from the initial imaging session to refine field-of-view alignment.

4.  Finally, the imaging plane was adjusted in the x-, y-, and z-axes until cellular features and other anatomical landmarks matched those in the reference images acquired at the target imaging depth, enabling reliable field-of-view and cell matching across imaging sessions.

### Imaging parameters

After stabilizing the imaging plane, PMT gain and laser power were adjusted to maximize signal-to-noise ratio and dynamic range while limiting saturation (\<1000 saturated pixels per frame). A predefined power lookup table guided parameter selection. Signal intensity between planes was balanced by adjusting beam power while monitoring pixel intensity histograms.

Laser power was selected from the [depth-dependent lookup ranges](#table-mesoscope-laser-power).

:::{table} Mesoscope laser power lookup ranges by imaging depth.
:label: table-mesoscope-laser-power
:enumerated: false
:class: table-accent table-compact table-laser-power table-hover-source

| Depth from surface (µm) | Minimum power (mW) | Maximum power (mW) |
| ---: | ---: | ---: |
| 0-50 | 0 | 30 |
| 50-100 | 25 | 50 |
| 100-150 | 50 | 80 |
| 150-200 | 70 | 100 |
| 200-250 | 90 | 125 |
| 250-300 | 110 | 170 |
| 300-350 | 150 | 180 |
| 350-400 | 160 | 190 |
| 400-450 | 200 | 240 |
| 450-500 | 200 | 240 |
| 500-550 | 200 | 240 |
| 550-600 | 200 | 240 |
:::

Two-photon imaging data (512 × 512 pixels; 11 Hz per plane for multi-plane acquisitions), eye tracking (30 Hz), and behavioral video (30 Hz) were recorded simultaneously and continuously monitored. Recording sessions were approximately 60 minutes in duration, with total imaging sessions lasting up to 75 minutes including setup and calibration. Sessions were terminated early if animals exhibited signs of stress (e.g., excessive periocular secretion, abnormal posture) or if data quality was compromised by technical issues, including loss of synchronization between data streams, photomultiplier tube (PMT) signal instability, or dropped imaging frames.

A total of 15 mice were allocated for the 2-photon workflow. The Sequence & Motor cohorts each consists of 5 completed data sets with each mouse undergoing 8 imaging sessions. Additional sessions were acquired as needed to replace datasets that failed quality control. 5 mice were removed from the workflow due to health-related issues.

### Quality control for two-photon calcium imaging

Quality control metrics were evaluated after each session. Sessions failing any criterion were repeated.

1.  **Image saturation:** Initial frames were inspected to ensure fewer than 1000 saturated pixels and adequate use of the detector dynamic range.

2.  **Photobleaching:** Baseline fluorescence at the beginning and end of the session was compared; sessions with \>20% signal loss were excluded.

3.  **Targeting accuracy:** Imaging locations were registered to ISI-derived maps to confirm correct visual area targeting.

4.  **Z-axis stability:** Mean images from the first and last 5 minutes were compared to a post hoc z-stack (±30 µm, 0.75 µm steps) to estimate drift. Sessions with \>10 µm drift were excluded.

5.  **Animal well-being:** Behavioral videos were reviewed for signs of stress (e.g., excessive secretion, orbital tightening, abnormal posture). Animals exhibiting sustained stress responses were removed from the experiment.

6.  **Temporal synchronization:** Alignment across all recorded data streams was verified.

7.  **System integrity:** Data streams were assessed for hardware or software failures affecting data quality.

8.  **Motion artifacts:** Residual motion was evaluated after motion correction.

9.  **Interictal activity:** Full-field fluorescence traces (first 10,000 frames) were analyzed for abnormal transient events. Sessions with potential interictal activity were manually reviewed and excluded if necessary [@steinmetz2017aberrant].

Metrics used for each criteria are available on the AWS S3 bucket in a qc.json file

### SLAP2 dendritic imaging.

Dual-color imaging of synaptic glutamate and somatic calcium in single neurons was performed using SLAP2. SLAP2 allows for simultaneous measurement of arbitrarily-shaped ROIs across two imaging planes. <span class="manuscript-wip-inline"><strong>Citation needed:</strong> add the SLAP2 methods paper when available.</span> We recorded from Layer 2/3 pyramidal neurons in the visual cortex. We imaged from soma and several peri-somatic dendritic segments in one plane, and imaged several apical dendritic segments on the second plane, typically achieving recordings of \>100 synapses at \>200 Hz each. Imaging was motion stabilized by using SLAP2’s image-based online motion correction.

#### Acquisition of reference stacks and ROI selection

Prior to functional imaging, structural reference stacks were acquired for motion correction and ROI definition. For each imaging plane, a z-stack consisting of 21 optical sections spaced 1 um apart was collected, averaging 35--45 repeated acquisitions per section . One reference stack was centered on the soma and proximal dendrites, whereas the second stack was centered on apical dendritic regions.

Reference stacks were aligned during the imaging session and used to define imaging ROIs. ROIs were drawn manually encompassing dendritic segments containing visually identifiable spines and algorithmically refined to exclude dark background pixels. Restricting ROIs to dendritic shafts and spines reduces the number of imaged pixels and increases sampling rate.

The reference stacks were also used for online motion correction during functional imaging. Lateral (x-y) displacements were estimated by registering incoming data to the reference volumes and were used to update the DMD illumination patterns in real time. Axial (z) motion was compensated independently using a remote-focusing system, allowing ROIs to remain aligned to the targeted neuronal structures throughout the recording session.

## Data processing

### Neuropixels extracellular electrophysiology.

Raw data was processed using the AIND ephys pipeline [@aind2026ephyspipeline] on the Code Ocean platform. In brief, the pipeline is implemented in Nextflow DSL2 and each probe was processed in parallel with the following steps:

- Preprocessing: including phase shift, highpass filter, bad channel detection and removal, common median reference

- Spike Sorting with Kilosort version 4

- Postprocessing: computing additional extensions (e.g., waveforms, spike amplitudes, PCA scores) and quality metrics

- Curation: applying quality-metric based thresholding and UnitRefine pre-trained classifiers [@jain2025unitrefine]

- Visualization and QC: generation of plots for quality control of raw and spike sorted data

For more details, please refer to [@buccino2026pipelines]

#### Identification of brain areas associated with Neuropixels nodes

After brains are processed in the imaging pipeline, neuroglancer ([https://neuroglancer-demo.appspot.com](https://neuroglancer-demo.appspot.com/)) is used to reconstruct probe tracks in the brain. Points are placed along the length of the probe track and are closely inspected to ensure annotation of the probe tip and each track is assigned to a particular day of recording.

Electrophysiology features recorded from neural probes are aligned with anatomical landmarks based on the Allen Mouse Brain Common Coordinate Framework (CCFv3) [@wang2020ccf]. For this, we use the IBL ephys alignment GUI ([https://github.com/AllenNeuralDynamics/ibl-ephys-alignment-gui](https://github.com/AllenNeuralDynamics/ibl-ephys-alignment-gui)). Based on firing rate, LFP power, as well as spike and LFP cross correlograms, we place reference lines delineating borders of areas. Through this procedure, we consistently align the top of the cortex (Layers 2/3, where we expect spiking activity) using cross correlograms. Other alignment locations such as white matter tracks, thalamus, and subcortical regions are only made when there are clear electrophysiological landmarks (i.e. a stark increase in firing rate for thalamus, a stark decrease in activity in white matter, etc). If features such as these are not present, the GUI’s probe track interpolation is accepted. Notably, this interpolation is accepted for cortical layer assignments between Layers 2/3 and the bottom of cortex. We also ensure that the channel assignments on the probe track are within 10% of the expected scaling factor.

### Two-photon mesoscope calcium imaging.

Raw two-photon calcium imaging data were processed using the AIND planar optical physiology pipeline (aind-pophys-pipeline v11 and v13; [https://github.com/AllenNeuralDynamics/aind-pophys-pipeline](https://github.com/AllenNeuralDynamics/aind-pophys-pipeline)) on the Code Ocean platform. The pipeline is implemented in Nextflow DSL2 and processes each imaging plane independently and in parallel through the following steps:

- Data conversion: For multiplane mesoscope data acquired with the dual-beam configuration, interleaved TIFF files were de-interleaved into individual imaging planes and stored as separate HDF5 timeseries using the aind-pophys-converter-capsule ([https://github.com/AllenNeuralDynamics/aind-pophys-converter-capsule](https://github.com/AllenNeuralDynamics/aind-pophys-converter-capsule)).

- Motion correction: Non-rigid (piecewise rigid) motion correction was performed on each plane using Suite2p [@pachitariu2016suite2p] ([https://github.com/MouseLand/suite2p](https://github.com/MouseLand/suite2p)), implemented in the aind-ophys-motion-correction capsule ([https://github.com/AllenNeuralDynamics/aind-ophys-motion-correction](https://github.com/AllenNeuralDynamics/aind-ophys-motion-correction)). Default parameters included a maximum registration shift of 10% of the field of view (maxregshift = 0.1), Gaussian spatial smoothing with σ = 1.15 pixels, a maximum non-rigid shift of 5 pixels per block (maxregshiftNR = 5), and a signal-to-noise threshold of 1.2 for block smoothing (snr_thresh = 1.2). Frames were processed in batches of 500.

- Decrosstalk: Because the dual-beam mesoscope acquires pairs of imaging planes with temporally offset excitation beams that are separated by analog demultiplexing, the incomplete capture of fluorescence decay within the 6.25 ns integration window produces approximately 10% inter-plane signal crosstalk. To correct this residual bleed-through, paired planes were identified from session metadata using the aind-ophys-group-planes capsule ([https://github.com/AllenNeuralDynamics/aind-ophys-group-planes](https://github.com/AllenNeuralDynamics/aind-ophys-group-planes)), and an independent component analysis (ICA)-based demixing algorithm was applied to the motion-corrected plane pairs using the aind-ophys-decrosstalk-roi-images capsule ([https://github.com/AllenNeuralDynamics/aind-ophys-decrosstalk-roi-images](https://github.com/AllenNeuralDynamics/aind-ophys-decrosstalk-roi-images)).

- Cell segmentation and trace extraction: Regions of interest (ROIs) corresponding to individual neurons were detected using a cell detection algorithm, implemented in the aind-ophys-extraction capsule ([https://github.com/AllenNeuralDynamics/aind-ophys-extraction](https://github.com/AllenNeuralDynamics/aind-ophys-extraction)).

  The default configuration used Suite2p's sparse detection mode (init = sparsery) with automatic diameter estimation (diameter = 0), a cell probability threshold of 0.0 (cellprob_threshold = 0.0), threshold scaling of 1, and a maximum overlap of 75% between ROIs (max_overlap = 0.75). For each detected ROI, a raw fluorescence trace was computed by averaging pixel intensities within the ROI footprint. Neuropil contamination was estimated from a surrounding annular region and subtracted using a neuropil correction coefficient determined by minimizing the mutual information between the corrected trace and the neuropil signal. Suite2p's built-in classifier was used to provide an initial cell/non-cell classification for each ROI.

- ROI classification: Following extraction, a GPU-accelerated ROI classification step was applied to each imaging plane using a pre-trained classifier (aind-ophys-classifier capsule). The classifier, trained using the ROICaT framework (Region Of Interest Classification and Tracking; [https://github.com/richiehakim/ROICaT](https://github.com/richiehakim/ROICaT)), categorized each detected ROI as a cell or non-cell based on learned spatial features. The classification results were stored in a separate classification.h5 file for each plane and used to label ROIs in the final NWB output.

- ΔF/F computation: Baseline-corrected fluorescence traces (ΔF/F) were computed from the neuropil-corrected traces using the aind-ophys-dff capsule ([https://github.com/AllenNeuralDynamics/aind-ophys-dff](https://github.com/AllenNeuralDynamics/aind-ophys-dff)). The algorithm proceeded as follows: (1) the noise standard deviation σ was estimated using the median absolute deviation (MAD) method; (2) an initial baseline b was estimated; (3) active frames were identified as outliers exceeding b + 3σ and masked; (4) the baseline fluorescence F₀ was obtained by median-filtering the trace over a 60 s sliding window using only inactive frames, with interpolation across masked segments; (5) ΔF/F was computed as (F − F₀) / F₀. A short window of 3.333 s was used for local noise estimation, and the inactive percentile was set to 10.

- Event detection: Deconvolved neural events were extracted from the ΔF/F traces using the OASIS algorithm [@friedrich2017fast]; ([https://github.com/j-friedrich/OASIS](https://github.com/j-friedrich/OASIS)), implemented in the aind-ophys-oasis-event-detection capsule ([https://github.com/AllenNeuralDynamics/aind-ophys-oasis-event-detection](https://github.com/AllenNeuralDynamics/aind-ophys-oasis-event-detection)). OASIS performs nonnegative deconvolution of calcium fluorescence traces to infer the underlying spike-related activity, modeling the calcium dynamics as an autoregressive process with an exponential decay kernel. The decay time constant, baseline, and sparsity penalty (Lagrange multiplier for the noise constraint) were automatically estimated from the data's autocovariance. The outputs include the inferred deconvolved activity (event rates), the denoised fluorescence trace, and the estimated model parameters for each ROI.

### SLAP2 dendritic imaging.

#### Post-hoc motion correction

Images were generated with an 80 Hz query timebase, and aligned using a custom algorithm (MultiRoiRegistration; [AllenNeuralDynamics/GIAnT-MATLAB (2026)](https://github.com/AllenNeuralDynamics/GIAnT-MATLAB)), as conventional motion correction algorithms are unstable when correcting motion in thin strip fields of view (Pnevmatikakis & Giovannucci, 2017). Our algorithm was implemented in MATLAB. In brief, the algorithm first initializes a template by using NoRMCorre (Pnevmatikakis & Giovannucci, 2017) to align 42 evenly-spaced frames throughout a trial. Each frame is then aligned against the template by finding the X and Y displacement that yields the maximum cross-correlation among imaged pixels. The pixel values and template values are square root transformed as variance stabilizing technique. Subpixel shifts are determined by fitting a 2-dimensional quadratic to the cross-correlation function around the maximum. With the displacement estimate, a motion corrected frame is generated by linear interpolation, weighted by the freshness of each contributing observation. The motion corrected frame is then averaged into the template to dynamically update it as frames become aligned.

#### Source extraction

Source extraction was performed with a custom algorithm (SILo; [AllenNeuralDynamics/GIAnT-MATLAB (2026)](https://github.com/AllenNeuralDynamics/GIAnT-MATLAB)), implemented in MATLAB. This algorithm takes advantage of the fact that glutamate release events are spatiotemporally sparse. Specifically, we take inspiration from superresolution localization microscopy methods (Lelek et al., 2021; Chen et al., 2025) to precisely identify source locations despite the reduced effective resolution produced by the integration over pixels. We model a single event as having a spatiotemporal profile of a small Gaussian dot (standard deviation of $1.33$ pixels) modulated over time by a decaying exponential of a time constant matched to the glutamate indicator (for iGluSnFR4f we use a decay constant of $\tau = 20$ ms). We perform event detection by convolving this shape with the movie to identify local maxima in space and time (i.e., a 3D matched filter). These events are weighted by their intensity in the filtered movie and aggregated into a summary image, which we term the *activity image*. The activity image shows localized densities around active sources. We then identify the centroids of these densities by fitting each to a symmetric Gaussian to establish the location of each synapse. As a final step, we use the established source locations as the initialization for constrained non-negative matrix factorization to fine tune the spatial profiles and extract their corresponding time traces.

### NWB data packaging

#### Eye tracking

At different points in each modality’s respective pipelines, eye tracking information is extracted from the raw behavior videos. A standardized capsule, aind-capsule-eye-tracking ([https://github.com/AllenNeuralDynamics/aind-capsule-eye-tracking](https://github.com/AllenNeuralDynamics/aind-capsule-eye-tracking)) was built for fitting ellipses to the pupil, eye (visible perimeter of the eyeball), and corneal reflection of the right eye, based on points tracked using the open source software DeepLabCut ([Mathis et al. 2018](https://www.nature.com/articles/s41593-018-0209-y)). DeepLabCut, which uses a pre-trained ResNet 50 deep residual network, was used to track (up to) 12 points along the perimeters of the eye, pupil, and corneal reflection. Ellipses were then fit to the tracking points and the ellipse fit parameters were saved to disk. Validation against hand-annotated ‘ground truth’ frames confirmed that a single ‘universal’ model, trained on a broad selection of data samples, robustly generalized on held-out data across different physiology rigs and individual animals

#### Synchronized Stimulus Table Generation - Ephys

The alignment of stimulus information to the electrophysiology recording is done using the legacy version of the aind-metadata-mapper ([https://github.com/AllenNeuralDynamics/aind-metadata-mapper/tree/legacy](https://github.com/AllenNeuralDynamics/aind-metadata-mapper/tree/legacy)) requires two input files: a sync file (HDF5, .sync) containing a binary counter sampled at approximately 100 kHz, where each bit encodes the state of a labeled digital line, and a stimulus pickle file (.stim.pkl) containing the intended stimulus parameters and timing as programmed by the stimulus control software (CamStim [https://github.com/AllenNeuralDynamics/camstim](https://github.com/AllenNeuralDynamics/camstim)). The pickle file stores, for each stimulus block, a sweep table of parameter values (e.g., orientation, contrast, spatial frequency), an array of sweep frame indices in stimulus-local coordinates, and a display sequence specifying when each block was presented in seconds relative to session start.

Frame times are extracted from the sync file using two digital lines: the vsync line (stim_vsync), whose falling edges mark nominal monitor frame boundaries, and the photodiode line (stim_photodiode), which records the output of a photodiode affixed to the stimulus monitor that toggles state every 60 frames. Because the photodiode signal reflects actual light output, it captures true frame timing including irregular refresh intervals that the vsync signal does not. The alignment procedure detects all photodiode transitions, trims pulses outside the vsync range, corrects for missing or spurious edges, and then allocates individual frame timestamps within each 60-frame photodiode interval using a trimmed-mean estimate of frame duration. Clock counter rollovers are detected and corrected by adding 2^32 offsets where negative intervals appear. The result is a one-dimensional array of frame times in seconds on the sync clock, one entry per monitor frame, with sub-millisecond precision.

To map stimulus parameters onto these frame times, each stimulus block's display sequence is converted from seconds to global frame indices using the monitor frame rate and pre-blank duration recorded in the pickle file. The stimulus-local sweep frame indices are then shifted into the global frame domain by apply_display_sequence(). Finally, convert_frames_to_seconds() indexes into the photodiode-corrected frame time array to assign each sweep a start time and stop time in sync-clock seconds. The output is a single stimulus table (saved as a CSV) in which each row corresponds to one stimulus sweep, with columns for start time, stop time, start frame, end frame, stimulus name, and all associated stimulus parameters. Gaps between stimulus blocks are filled with rows labeled as spontaneous activity.

#### Synchronized Stimulus Table Generation - Mesoscope

The mesoscope alignment uses the same, aind-metadata-mapper ([https://github.com/AllenNeuralDynamics/aind-metadata-mapper](https://github.com/AllenNeuralDynamics/aind-metadata-mapper)) and the same two input files: a sync file containing digital line states sampled at approximately 100 kHz, and a stimulus pickle file containing the programmed stimulus sweep parameters and timing. The processing diverges from the ephys pipeline in how frame times are derived from the sync data.

Rather than using the photodiode to reconstruct per-frame timing, the mesoscope pipeline takes the falling edges of the vsync line as the base frame times directly. The photodiode is instead used to measure the delay between when the computer issues a vsync signal and when the monitor actually displays the frame. This is done by extract_frame_times_with_delay(), which detects a characteristic three-pulse photodiode pattern marking stimulus onset and offset, then computes, for each photodiode transition in between, the difference between the photodiode rising edge and the nearest vsync falling edge. The median of these per-pulse delays — typically around 35.6 ms — is added uniformly to all vsync-derived frame times. If the measurement is unreliable (standard deviation exceeding 2 ms, or missing data), a hardcoded fallback delay of 0.0356 seconds is applied instead.

Once delay-corrected frame times are established, the mapping from stimulus sweeps to seconds proceeds identically to the ephys case: display sequences are converted to global frame indices, local sweep frames are remapped into the global domain, and frame indices are converted to seconds by lookup in the frame time array. The mesoscope pipeline produces two output tables. The primary table uses the delay-corrected frame times and is appropriate for analyses correlating neural calcium signals with stimulus events, since both the imaging and the stimulus share the same monitor display latency. The secondary table uses raw vsync times without the delay correction, which is useful for analyses tied to hardware trigger signals. Both tables have the same columnar structure: one row per sweep, with start time, stop time, frame indices, stimulus name, and stimulus parameters.

#### SLAP2 synchronization

SLAP2 imaging, visual-stimulus, running-wheel, and camera timing were synchronized using signals recorded by the HARP Behavior device. The synchronization and packaging implementation is contained in the [SLAP2 NWB packaging capsule](https://codeocean.allenneuraldynamics.org/capsule/11f8d942-a12c-44b5-84db-d084164294d1/tree) and its source repository ([AllenNeuralDynamics/slap2_packaging_nwb](https://github.com/AllenNeuralDynamics/slap2_packaging_nwb)). HARP records the analog photodiode and wheel-encoder channels, the primary-plane SLAP2 cycle-clock digital input, SLAP2 trial-start and trial-end pulses, and grating-presentation pulses. All of these timestamps are placed on a common session time base by subtracting the timestamp of the first SLAP2 start pulse.

Stimulus parameters and durations are read from the stimulus-control orientation table and paired in order with the HARP grating-presentation pulse times. A discrepancy of at most three records is treated as an acquisition-boundary mismatch and resolved by removing unmatched leading records from the longer sequence; larger discrepancies cause packaging to fail. Each presentation start time is taken from its normalized HARP pulse, its stop time is calculated from the programmed duration, and the presentation is associated with the SLAP2 trial whose start and end pulses contain it. Presentations are then separated by stimulus block type and stored as NWB `TimeIntervals` tables with the synchronized start and stop times, trial index, and stimulus parameters.

Fluorescence samples are synchronized at finer resolution using the primary-plane cycle clock and the scan-line index associated with every extracted sample. Rising edges of the HARP cycle-clock signal define the start of each DMD1 imaging cycle; falling edges are not used because they do not reliably mark cycle ends. For trial-based sessions, the cycle stream is divided at inter-cycle gaps greater than five times the median cycle period. The number of cycles assigned to each trial is checked against the cycle count read from the SLAP2 `.dat` file, with a scan-line-based estimate used when that count is unavailable. Continuous sessions, and trial-based sessions for which gap detection does not yield the expected number of trials, use sequential cycle assignment based on the recorded cycle counts or scan-line totals. An extra leading HARP cycle group is removed only when the processed experiment summary, HARP gaps, and available `.dat` trial numbers jointly identify it as unmatched acquisition data.

Within each trial, an effective lines-per-cycle value is calculated from the maximum recorded scan-line index and the number of detected HARP cycles. Samples are assigned to cycles from their scan-line indices and linearly interpolated between consecutive cycle-start timestamps; the final cycle end is estimated from the mean measured cycle period. If the sample-derived and HARP-derived cycle counts disagree, timestamps are interpolated across the complete trial as a fallback. Because both DMDs share the same physical scanner but only DMD1 supplies the HARP cycle clock, the DMD1 alignment also produces scan-line-to-time control points at each cycle boundary. DMD2 sample times are obtained by interpolating its independently recorded scan-line indices against those control points. The pipeline verifies expected sample counts and strictly increasing timestamps and writes diagnostic plots of cycle periods, trial assignments, line-index corrections, and residual timing behavior.

#### Mesoscope 2-Photon Imaging NWB Packaging Pipeline

All processed data were packaged into Neurodata Without Borders (NWB) format [@rubel2022nwb]. NWB packaging was performed as an integrated step of the 2-Photon processing pipeline (mentioned above) which produced NWBs in the Zarr format containing the processed 2-Photon data.

A secondary pipeline, also run in nextflow DSL2 on the CodeOcean platform ([https://codeocean.allenneuraldynamics.org/capsule/8980147/tree](https://codeocean.allenneuraldynamics.org/capsule/8980147/tree)) consolidated all processing outputs together with raw synchronization data and behavioral data into a single NWB file per session. This included several steps run in parallel, whose outputs were merged into the final combined NWB:

- Converting the Pophys processing pipeline’s Zarr NWB to an h5py NWB using a capsule NWB-Zarr-HDMF-Conversion ([https://github.com/AllenNeuralDynamics/NWB-Zarr-HDMF-Conversion](https://github.com/AllenNeuralDynamics/NWB-Zarr-HDMF-Conversion))

- Generating a synchronized stimulus table that is time-aligned to the recorded ophys timing. Described above under “Synchronized Stimulus Table Generation - Mesoscope” This is then split into several intervals tables based on the type of stimulus shown and packaged into a copy of the ophys NWB.

- Processing the behavior videos of the eye into eye tracked output. Described above in “Eye Tracking”

- Aligning the eye tracking output to the recorded synchronized timing and packaging it into a copy of the ophys NWB, using a capsule aind-eye-tracking-nwb ([https://github.com/AllenNeuralDynamics/aind-eye-tracking-nwb](https://github.com/AllenNeuralDynamics/aind-eye-tracking-nwb))

- Aligning the running speed traces to the recorded synchronized timing and packaging it into a copy of the ophys NWB, using a capsule aind-running-speed-nwb ([https://github.com/AllenNeuralDynamics/aind-running-speed-nwb](https://github.com/AllenNeuralDynamics/aind-running-speed-nwb))

- Generating a new data description.json that references the input data, and includes the name of the newly generated data. Aggregating processing.json output from the eye tracking processing and the stim table generation into a new processing.json. Copying the remaining inputted metadata jsons (including procedures.json, quality_control.json, rig.json, session.json, subject.json)

- Finally, merging the resulting NWBs; the stimulus table NWB, the running speed NWB, and the eye tracking NWB, into one complete NWB using aind-nwb-utils ([https://github.com/AllenNeuralDynamics/aind-nwb-utils](https://github.com/AllenNeuralDynamics/aind-nwb-utils))

- The NWBs were then uploaded to their dandiset using the DANDI command line interface ([https://github.com/dandi/dandi-cli](https://github.com/dandi/dandi-cli))

#### Neuropixels Ephys NWB Packaging Pipeline

The processed data were also packaged into an NWB file during their respective processing pipeline mentioned above. This pipeline included two capsules which were run in sequence, appending processed ecephys information to a base subject NWB. They were aind-ecephys-nwb ([https://github.com/AllenNeuralDynamics/aind-ecephys-nwb](https://github.com/AllenNeuralDynamics/aind-ecephys-nwb)), which packaged LFP, electrode information, and device metadata, followed by aind-units-nwb ([https://github.com/AllenNeuralDynamics/aind-units-nwb](https://github.com/AllenNeuralDynamics/aind-units-nwb)) which packaged the units table of the units outputted from kilosort and their associated processed and postprocessed metric into the NWB.

A secondary pipeline, also run on the CodeOcean platform, took the output spike sorted NWB and the raw synchronization and behavior data to produce a complete NWB. This was done by appending data to the NWB in a sequence of processing capsules. This included;

- Converting the Spike sorting processing pipeline’s Zarr NWB to an h5py NWB using a capsule NWB-Zarr-HDMF-Conversion ([https://github.com/AllenNeuralDynamics/NWB-Zarr-HDMF-Conversion](https://github.com/AllenNeuralDynamics/NWB-Zarr-HDMF-Conversion))

- Using a synchronized stimulus table that is time-aligned to the recorded ecephys timing, this was generated prior to CodeOcean upload performed on Allen Institute rig computers. This process is described above under “Synchronized Stimulus Table Generation - Ephys” This table is then split into several intervals tables based on the type of stimulus shown and packaged into the NWB

- Processing the behavior videos of the eye into eye tracked output. Described above in “Eye Tracking”.

- Aligning the eye tracking output to the recorded synchronized timing and packaging it into the NWB, using a capsule called aind-eye-tracking-nwb ([https://github.com/AllenNeuralDynamics/aind-eye-tracking-nwb](https://github.com/AllenNeuralDynamics/aind-eye-tracking-nwb))

- Aligning the running speed traces to the recorded synchronized timing and packaging it into the NWB, using a capsule called aind-running-speed-nwb ([https://github.com/AllenNeuralDynamics/aind-running-speed-nwb](https://github.com/AllenNeuralDynamics/aind-running-speed-nwb))

- The NWBs were then uploaded to their dandiset using the DANDI command line interface ([https://github.com/dandi/dandi-cli](https://github.com/dandi/dandi-cli))

#### SLAP2 NWB Packaging Pipeline

SLAP2 data were packaged by a [Code Ocean pipeline](https://codeocean.allenneuraldynamics.org/pipelines/f8d26d18-3daf-45fd-9671-32b68d2a9441) whose principal synchronization and NWB assembly step is the [SLAP2 NWB packaging capsule](https://codeocean.allenneuraldynamics.org/capsule/11f8d942-a12c-44b5-84db-d084164294d1/tree). The capsule combines the raw SLAP2 session, the processed experiment-summary output from the motion-correction and source-extraction workflow, HARP data, stimulus tables, and the eye-tracking output described above. It can create a metadata-populated base NWB with `aind-nwb-utils` or append to a supplied NWB in HDF5 or Zarr form. The resulting file contains the synchronized neural, stimulus, locomotion, and eye-tracking data for one session.

The packaging procedure includes the following steps:

- Reading `instrument.json` and `acquisition.json` to register the SLAP2 microscope, optical channels, excitation and emission wavelengths, indicators, targeted structures, acquisition rates, and one NWB `ImagingPlane` for each DMD imaging path.

- Applying the SLAP2-HARP alignment described above to the processed fluorescence arrays from both DMDs. Candidate raw acquisitions are reconciled with the processed trial count across both planes so that the same acquisition and any excluded leading trials are used consistently.

- Creating an `ImageSegmentation` interface with one `PlaneSegmentation` per DMD. Three-dimensional source profiles are maximum-projected along z and stored as weighted NWB pixel masks, with additional columns retaining the minimum and maximum active z indices for each source.

- Packaging the synchronized baseline fluorescence (`F0`) and calculated dF/F traces for each available green or red channel as `RoiResponseSeries` objects linked to the corresponding ROI table. Registered, motion-corrected mean images for each channel and the source-extraction activity image are stored as `ImageSeries` objects in the `ophys` processing module.

- Converting the synchronized stimulus records into separate `TimeIntervals` tables by block type. HARP wheel-encoder samples are retained as raw signed counter values and are also unwrapped and converted to wheel rotation and linear running speed in the `running` processing module. The common eye-tracking procedure described above is joined to authoritative per-frame HARP camera timestamps by video frame number and added to the same NWB file.

- Generating synchronization, running, eye-tracking, receptive-field, and stimulus-tuning quality-control outputs. The capsule also writes structured processing provenance that records the stimulus-table conversion, SLAP2-HARP synchronization, and ophys NWB packaging steps and their dependencies.

Completed SLAP2 NWB files were deposited in [DANDI:001424](https://dandiarchive.org/dandiset/001424) alongside the Neuropixels and mesoscope releases.

::::

# Data records

## Data tables

Animal and session coverage, recording context, and quality-control status are summarized in [Figure 4](#fig-recording-session-inventory).

:::{iframe} ./interactive/data-explorer.html
:label: fig-recording-session-inventory
:width: 100%
:title: Recording-session inventory and quality control across modalities
:placeholder: ./images/figures/generated/session-inventory.svg

Recording-session inventory and quality-control summary across modalities. The
**Interactive** view provides searchable, filterable tables sourced from local
CSV snapshots, with expandable animal metadata and CSV export. The Sessions
table includes records with a valid session ID whose QC status is `Pass`. The
**Static** view summarizes the complete worksheet inputs used by the supplied
modality plots. Failed sessions are unfilled with borders colored by session
type; numbered markers identify descriptive QC tags listed in the legend. Across panels,
indigo, teal, brown, and gold
denote sensorimotor, standard oddball, sequence, and duration sessions,
respectively. Mice are ordered by cohort; where both are present, whitespace
separates the motor-first and sequence-first groups defined in [Figure 1C](#fig-graphical-abstract).
Repeated and aborted worksheet rows are retained in the Static view and excluded from the pass-QC Interactive Sessions table.
:::
## NWB file contents

All data from this project are packaged as Neurodata
Without Borders (NWB) files and deposited on the DANDI Archive. Neuropixels
electrophysiology sessions are available at
[DANDI:001637](https://dandiarchive.org/dandiset/001637), mesoscope two-photon
imaging sessions at [DANDI:001768](https://dandiarchive.org/dandiset/001768),
and SLAP2 dendritic-imaging sessions at
[DANDI:001424](https://dandiarchive.org/dandiset/001424). Use the tabs below as
a map from a scientific question to the corresponding NWB object and PyNWB
entry point. Object names can differ slightly among sessions; the paths shown
here reflect representative files in these Dandisets.

::::{tab-set}
:::{tab-item} Shared

**Shared across modalities:** session context, behavior, and stimulus timing
use the same acquisition clock, making these objects the starting point for
aligned analyses.

| Question | NWB contents | Representative PyNWB entry point |
| --- | --- | --- |
| When and from which animal was the session recorded? | Root session metadata and `/general/subject` contain the session ID and datetime, institution, subject ID, species, age, sex, and genotype. | `nwbfile.session_id`, `nwbfile.session_start_time`, `nwbfile.subject` |
| What stimulus was shown at each time? | `/intervals/*_presentations` contains one `TimeIntervals` table per block. Rows include `start_time`, `stop_time`, and stimulus parameters such as orientation, spatial and temporal frequency, contrast, position, phase, and trial type. | `nwbfile.intervals[table_name].to_dataframe()` |
| When was no stimulus presented? | `/intervals/spontaneous_presentations` marks gaps between stimulus blocks. | `nwbfile.intervals["spontaneous_presentations"]` |
| Was the animal moving? | `/processing/running` contains synchronized wheel rotation and computed running speed. | `nwbfile.processing["running"]["running_speed"]` |
| Was the animal looking at the display? | When available, `/processing/eye_tracking` contains pupil, corneal-reflection, and eye ellipse fits plus likely-blink intervals. | `nwbfile.processing["eye_tracking"]` |

:::
:::{tab-item} Neuropixels

**Neuropixels NWB files ([DANDI:001637](https://dandiarchive.org/dandiset/001637)):**
connect spike-sorted units to their probes, anatomical positions, quality
metrics, and local field potentials.

| Question | NWB contents | Representative PyNWB entry point |
| --- | --- | --- |
| Which units were isolated, and do they pass quality control? | `/units` contains firing rate, ISI violations, presence ratio, amplitude cutoff, SNR, d-prime, isolation distance, silhouette score, sliding refractory-period violations, and a default QC flag. | `nwbfile.units.to_dataframe()` |
| When did a unit spike, and what was its waveform? | Ragged `spike_times` plus mean and standard-deviation waveforms are columns of `/units`. | `nwbfile.units["spike_times"][unit_row]` |
| Where was each unit recorded? | Unit rows identify the probe and electrode and include estimated 3D coordinates. `/general/extracellular_ephys/electrodes` describes every channel, probe group, and shank-relative position. | `nwbfile.electrodes.to_dataframe()` |
| Which probes were used? | `/general/devices` registers up to six Neuropixels probes and their serial numbers. | `nwbfile.devices` |
| What was the local population signal? | `/processing/ecephys/LFP` contains downsampled local field potential per probe (96 channels at approximately 2,500 Hz). | `nwbfile.processing["ecephys"]["LFP"]` |

:::
:::{tab-item} Mesoscope

**Mesoscope NWB files ([DANDI:001768](https://dandiarchive.org/dandiset/001768)):**
organize optical physiology by imaging plane so ROIs, traces, events, and
summary images remain connected.

| Question | NWB contents | Representative PyNWB entry point |
| --- | --- | --- |
| Where and how was each plane imaged? | `/general/optophysiology` describes eight simultaneous VISp and VISl planes, including excitation wavelength, imaging rate, grid spacing, indicator, cortical location, and field-of-view origin. The mesoscope is registered under `/general/devices`. | `nwbfile.imaging_planes`, `nwbfile.devices` |
| Which pixels belong to each ROI? | `/processing/<plane>/image_segmentation` contains 512 × 512 px ROI masks with dendrite probability scores. | `nwbfile.processing[plane]["image_segmentation"]` |
| How does fluorescence change over time? | Each plane contains raw, neuropil, neuropil-corrected, and ΔF/F time series. | `nwbfile.processing[plane]["dff_timeseries"]` |
| Where are inferred neural events? | Each plane's `event_timeseries` stores deconvolved event traces. | `nwbfile.processing[plane]["event_timeseries"]` |
| What does the field of view look like? | Each plane's `images` interface contains average projection, maximum projection, and segmentation-mask summary images. | `nwbfile.processing[plane]["images"]` |

:::
:::{tab-item} SLAP2

**SLAP2 NWB files ([DANDI:001424](https://dandiarchive.org/dandiset/001424)):**
connect source masks, mean and activity images, and fluorescence traces within
each DMD imaging path.

| Question | NWB contents | Representative PyNWB entry point |
| --- | --- | --- |
| Where and how was each DMD path imaged? | `/general/optophysiology` describes the DMD1 and DMD2 imaging planes, optical channels, device, indicator, and field geometry. | `nwbfile.imaging_planes`, `nwbfile.devices` |
| Which pixels belong to each extracted source? | `/processing/ophys/ImageSegmentation/PlaneSegmentation_DMD*` stores one weighted `pixel_mask` per source. | `nwbfile.processing["ophys"]["ImageSegmentation"]` |
| What source and structural images are available? | `/processing/ophys/DMD*_mean_image_channel*` stores mean channel images, and `DMD*_activity_image` stores the source-localization activity projection. | `nwbfile.processing["ophys"]["DMD1_activity_image"]` |
| How does each source change over time? | `/processing/ophys/Fluorescence_DMD*/DMD*_dFF` stores source ΔF/F with timestamps; the corresponding `DMD*_F0` series stores baseline fluorescence. | `nwbfile.processing["ophys"]["Fluorescence_DMD1"]["DMD1_dFF"]` |

:::
::::

NWB files can be streamed directly from DANDI without downloading the complete
asset; see the [data access code example](#data-access-code-example) below. The
[OpenScope Databook](https://alleninstitute.github.io/openscope_databook)
provides companion analysis notebooks for selecting sessions and working with
the electrophysiology, imaging, and behavioral objects introduced here.

# Data validation

## Raw data across recording modalities

Representative native acquisition formats and source-backed excerpts are shown in [Figure 5](#fig-aligned-neural-signals).

:::{iframe} ./interactive/neural-viewer.html
:label: fig-aligned-neural-signals
:width: 100%
:title: Raw recording excerpts across modalities
:placeholder: ./images/figures/generated/raw-neural-recordings.svg

Representative raw-data excerpts from one public session per recording modality,
shown to introduce the native acquisition formats. The **Interactive** view
supports source selection, contrast adjustment, and microscopy playback. The
microscopy contrast control applies black-referenced display gain. The
**Static** view arranges all available recordings as overlapping raw-image cards
without playback controls:
**A,** all six Neuropixels probe heatmaps stacked with CCF anatomy; **B,** all
eight mesoscope plane stills in two four-card stacks spanning VISp and VISl; and
**C,** two merged SLAP2 plane previews spanning two VISp depths (one per DMD),
with iGluSnFR4f shown in green and RCaMP3 in red.
Covered cards retain exposed labels and raw-image strips to convey the complete
acquisition scale. Static mesoscope stills are independently stretched to their
1st–99.5th max-channel percentiles. Each SLAP2 preview merges the two channels,
independently scaled to their 1st–99.5th sampled-pixel percentiles, from a
single aligned source frame without temporal averaging, then applies a
hue-preserving gamma of 0.55 for display. Neuropixels views contain
100 ms of calibrated, unaveraged 30-kHz voltage from 96 regularly spaced
contacts in the raw AP acquisition stream supplied to spike sorting; the
adjacent CCF column and horizontal boundaries identify each contact's annotated
structure or cortical layer. The displayed AP samples are not median-corrected,
so common-mode fluctuations across contacts remain visible as vertical stripes.
Mesoscope views are unprocessed 512 × 512 ScanImage channel frames. SLAP2 views
map native sparse detector samples onto acquisition-plan superpixels, reduce the
stored 1280 × 800 acquisition-coordinate raster by 2×, transpose it for
publication display, and encode the resulting 400 × 640 lossless WebP frames,
with the fast-scanning x axis vertical. A dim structural reference is used only outside
sampled dendritic pixels. Microscopy
playback uses elapsed time within each four-second excerpt. Selectors report CCF
structures and layers for each probe; area, layer, and depth for each mesoscope
plane; and indicator plus remote-focus depth below pia (91 µm for DMD1 and
123.75 µm for DMD2) for each SLAP2 field. Microscopy intensity is pseudocolored
and contrast-scaled independently for display. Source sessions are Neuropixels
[ecephys_830846_2026-03-09_10-32-54](https://open.quiltdata.com/b/aind-open-data/tree/ecephys_830846_2026-03-09_10-32-54/) ([DANDI:001637](https://dandiarchive.org/dandiset/001637/draft/files));
mesoscope [multiplane-ophys_832700_2026-01-29_11-18-09](https://open.quiltdata.com/b/aind-open-data/tree/multiplane-ophys_832700_2026-01-29_11-18-09/) ([DANDI:001768](https://dandiarchive.org/dandiset/001768/draft/files));
and SLAP2
[796630_2025-08-28_14-25-34](https://open.quiltdata.com/b/aind-open-data/tree/796630_2025-08-28_14-25-34/) ([DANDI:001424](https://dandiarchive.org/dandiset/001424/draft/files)).
:::

## Units extraction

Representative unit-extraction filters and matched activity traces are shown in
[Figure 6](#fig-segmentation-viewers).

:::{iframe} ./interactive/segmentation-viewer.html
:label: fig-segmentation-viewers
:width: 100%
:title: Unit extraction across recording modalities
:placeholder: ./images/figures/generated/figure-06-segmentation-viewers.svg

Unit extraction filters and matched activity across recording modalities.
Modality tabs use the same platform logos as the other multimodal figures, and
the source selector switches among every probe or imaging plane in one
representative session. The tabs use the same representative sessions as the
raw-data view in [Figure 5](#fig-aligned-neural-signals) and derive their
filters and traces from the matched public NWBs. The **Neuropixels** tab
provides all six probes from `ecephys_830846_2026-03-09_10-32-54`. Each source displays
100 ms of unaveraged AP voltage with sorted-spike detections overlaid at their
spike times and nearest displayed peak channels; common-mode correction is
enabled by default and can be toggled to reveal the uncorrected samples.
Selecting a marker or unit highlights its depth and waveform-spread band and
shows a 12 s binned-rate trace plus its peak-channel mean template. The
**Mesoscope** tab provides all eight VISp and VISl planes from
`multiplane-ophys_832700_2026-01-29_11-18-09`,
outlining each plane's complete NWB segmentation over a grayscale average
projection; selection reveals classification probabilities, footprint geometry,
and a 30 s ΔF/F (%) trace. The **SLAP2** tab provides DMD1 and DMD2 from
`SLAP2_796630_2025-08-28-14-25-34`, outlining each plane's complete source
segmentation over a grayscale mean image; its column-major stored (x, y) arrays
and masks receive the same publication-level axis transpose. Mesoscope
projections retain their stored display orientation. The fast-scanning x axis
is horizontal for mesoscope and vertical for SLAP2. SLAP2 selection
reveals a 30 s, approximately 200 Hz ΔF/F (%) trace. Microscopy background controls alter only
grayscale image intensity, while filter colors remain fixed. No tab shows
stimulus annotations. The stacked static fallback preserves one representative
source per modality and shows twenty activity-bearing filters sampled evenly across
filter order as vertically stacked traces with shared within-modality scales.
Data come from the public drafts of
[DANDI:001637](https://dandiarchive.org/dandiset/001637/draft/files),
[DANDI:001768](https://dandiarchive.org/dandiset/001768/draft/files), and
[DANDI:001424](https://dandiarchive.org/dandiset/001424/draft/files).
:::

:::{warning} Work in progress
:class: manuscript-wip
[Figure 7](#fig-unit-extraction-plan) and the modality subsections below remain an analysis outline. The Neuropixels unit-yield result is current; the other signal-quality, stability, extraction, and cross-session analyses still need final results and prose.
:::

:::{figure} ./images/figures/generated/figure-07-unit-extraction-plan.svg
:label: fig-unit-extraction-plan
:alt: Draft panel plan for unit extraction and signal-to-noise analysis across modalities.
:width: 100%

Draft plan for unit extraction and signal-to-noise analysis across recording modalities.
:::

### Neuropixels recordings

- signal-to-noise

- Stability across one session

- Quality control

- To support repeated targeting while avoiding blood vessels, each probe's entry point was shifted slightly from its position on the previous day. Across 60 unit-bearing sessions from 16 mice, mean QC-passing unit yield per recorded probe declined from 100% of the day-1 baseline to 80.9% on day 4 ([Supplementary Figure 2](#fig-supp-neuropixels-unit-yield)).

### Mesoscope two photon imaging

GROUP 1

- Motion correction across planes in one session and many sessions.

GROUP 2

- ROI extraction quality

- DFF signal quality (stability of baseline, calcium kernel)

GROUP 2.2

- Event extraction quality (firing rate, the SNR of events, calcium kernel …)

GROUP3

- Cell matching across sessions 2P,Cell stability across sessions.

- TOOLS ACROSS

### SLAP imaging

- signal-to-noise

- Quality control

- Bleaching

## Receptive field analysis across modalities

:::{warning} Work in progress
:class: manuscript-wip
This analysis and [Figure 8](#fig-basic-stimuli-plan) are planning placeholders. Receptive-field methods, cross-modality results, and final figure panels still need to be added.
:::

:::{figure} ./images/figures/generated/figure-08-basic-stimuli-plan.svg
:label: fig-basic-stimuli-plan
:alt: Draft panel plan for basic stimulus responses across recording modalities.
:width: 100%

Draft plan for basic stimulus characterization across recording modalities.
:::

## Behavioral data analysis across modalities

For sessions with camera acquisition, the release includes continuous raw
behavioral videos together with synchronized running-wheel signals, processed
eye-tracking outputs, and stimulus-presentation intervals. Depending on the
recording platform, the available views include body or behavior, face, eye,
and nose cameras. The synchronized multimodal examples in
[Figure 9](#fig-behavior-tracking) show these streams alongside the wheel signal and
current stimulus state. Existing NWB products provide wheel rotation and
running speed, plus pupil, corneal-reflection, and eye-ellipse fits with
likely-blink flags. The underlying videos remain available so investigators can
derive additional behavioral measurements while preserving alignment to the
stimulus and neural or imaging data.

These synchronized videos are therefore open to more sophisticated reanalysis,
including markerless pose and keypoint tracking with
[DeepLabCut](https://github.com/DeepLabCut/DeepLabCut),
[SLEAP](https://sleap.ai/), [Lightning Pose](https://lightning-pose.readthedocs.io/),
or other computer-vision methods. Potential derived features include facial and
body motion energy, posture, grooming, locomotor state, pupil dynamics, and
trial-resolved behavioral responses. Camera frames are tied to the acquisition
clock through 100-kHz exposure or readout edges for Neuropixels and mesoscope
sessions and per-frame Harp timestamps for SLAP2, allowing newly derived
features to be registered to wheel, stimulus, electrophysiology, and imaging
signals.

:::{iframe} ./interactive/behavior-viewer.html
:label: fig-behavior-tracking
:width: 100%
:title: Synchronized behavior, locomotion, and visual stimuli across recording modalities
:placeholder: ./images/figures/generated/synchronized-behavior.svg

Synchronized behavior and running across recording modalities. **A–C,** Camera
views and complete-session running profiles from representative Neuropixels
(**A**), mesoscope (**B**), and SLAP2 (**C**) sessions. Each row pairs all
available camera views with the running profile from the same mouse and source
session. Neuropixels and mesoscope stills retain the common 8-second synchronized
excerpt selection; the SLAP2 stills are sampled at 600 seconds from the
full-session profile source. Five-second profile means share one time axis and
are shown over measured standard, context, standard-repeat, sequence, jitter,
open-loop, natural-movie, and receptive-field block boundaries using the Figure
2 block colors. **D,** Mean forward running speed in each protocol block for
Neuropixels, mesoscope, and SLAP2, compared on one shared cm/s axis. Each point is
one mouse after averaging its available complete sessions, and each bar is the
mean across mice for its modality; legend values report included mice. The
**Interactive** view provides synchronized camera playback, running signals,
and reconstructed stimulus state for the selected modality. Metrics use
50 ms bins, and negative velocity is set to zero before summarization. SLAP2 encoder values
are converted to cm/s using the pinned
acquisition convention of 8192 counts/revolution, an 8.255 cm disc radius, and a
2/3 effective running radius. Each static camera image is
independently illuminated using its 1st–99th luminance percentiles and a bounded
gamma that maps median luminance to 35%, with exact parameters retained in
provenance. Behavior-camera video is
range-streamed from the public
`aind-open-data` S3 bucket. For Neuropixels and mesoscope sessions, NWB running
speed and stimulus rows share the sync-file clock with 100-kHz camera
exposure/readout edges; reported dropped frames are removed before mapping
hardware frame indices to MP4 presentation time. SLAP2 camera frames use
per-frame Harp timestamps on the acquisition clock. Camera and source selectors
expose the underlying public data without bundling multi-gigabyte videos into
the publication.
:::

### Eye tracking across modalities

Processed eye tracking provides a second synchronized view of behavior beyond
locomotion. [Supplementary Figure 4](#fig-supp-eye-tracking) aligns the public eye-camera
video, reconstructed visual stimulus, pupil-center position, pupil area, and
likely-blink flags for representative standard-oddball Neuropixels, mesoscope,
and SLAP2 sessions. The moving marker encodes pupil center in the full camera
frame; its size and color encode pupil area relative to the 5th–95th percentile
range from that complete session. A crosshair marks the robust full-session
median pupil center. During likely blinks, the tracking field turns black and
the corresponding samples are shaded in the pupil-area trace. A shared playback
cursor makes the timing relationship between all three streams explicit.

## Stimulus-evoked responses: oddball across modalities

:::{warning} Work in progress
:class: manuscript-wip
This analysis, the questions below, and [Figure 10](#fig-standard-oddball-plan) are planning placeholders. Final cross-modality oddball-response results and figure panels still need to be added.
:::

- Stability across the session for all modalities ?

- Orientation tuning plots?

:::{figure} ./images/figures/generated/figure-10-standard-oddball-plan.svg
:label: fig-standard-oddball-plan
:alt: Placeholder slide for standard oddball responses and stimulus alignment.
:width: 100%

Placeholder for standard oddball responses across recording modalities.
:::

# Usage Notes

(data-access-code-example)=
## Data access code example

The following Python example streams an HDF5 NWB file directly from DANDI using
HTTP range requests, without first downloading the complete file. Install the
required packages with `python -m pip install dandi h5py pynwb remfile`. Set
`DANDISET_ID` to `001637` for Neuropixels data or `001768` for mesoscope data;
for reproducible analyses, replace `draft` and the automatically selected asset
with a published version and explicit asset path.

```{code-cell} python
:tags: [skip-execution]

import h5py
import remfile
from dandi.dandiapi import DandiAPIClient
from pynwb import NWBHDF5IO

DANDISET_ID = "001637"  # Use "001768" for mesoscope data.
DANDISET_VERSION = "draft"

with DandiAPIClient() as client:
    dandiset = client.get_dandiset(DANDISET_ID, version_id=DANDISET_VERSION)
    asset = next(
        asset for asset in dandiset.get_assets() if asset.path.endswith(".nwb")
    )
    download_url = asset.get_content_url(follow_redirects=1, strip_query=True)

remote_file = remfile.File(download_url)
h5_file = h5py.File(remote_file, mode="r")
with NWBHDF5IO(file=h5_file, mode="r", load_namespaces=True) as io:
    nwbfile = io.read()
    table_name = next(iter(nwbfile.intervals))
    intervals = nwbfile.intervals[table_name].to_dataframe()

    print(f"Streaming: {asset.path}")
    print(f"Session: {nwbfile.session_id}")
    print(f"Intervals table: {table_name}")
    print(intervals.head())

remote_file.close()
```

The [OpenScope Databook](https://alleninstitute.github.io/openscope_databook/)
provides additional notebooks for downloading files, selecting sessions, and
working with electrophysiology, imaging, and behavioral data.

## Limitations

:::{warning} Work in progress
:class: manuscript-wip
The final limitations discussion still needs to be drafted. Topics already identified include passive-viewing constraints and incomplete cell-type coverage; additional modality-specific and sampling caveats should be added.
:::

## Data analysis plan

:::{warning} Work in progress
:class: manuscript-wip
This section is an unedited working outline. It needs substantial shortening and reorganization around a prioritized set of hypotheses, prespecified outcomes, shared cross-modality analyses, and clearly separated confirmatory and exploratory tests.
:::

Our review [@aizenbud2026neural] highlighted the presence of mismatch responses throughout the cortical network, spanning multiple areas and cellular populations, including excitatory neurons and inhibitory subtypes. These responses involve dynamic contributions from both dendritic and somatic compartments. Consequently, our analysis must disentangle these relative contributions within a tightly integrated network, across multiple types of mismatches.

A key assumption in our analysis is that different types of mismatches may recruit distinct relative contributions from computational primitives. To test this assumption, we must measure the precise dynamic properties of individual compartments across neuronal types, areas and layers. Our goal is to compare the relative timing and strength of predictive responses, complemented by decoding analyses to extract instantaneous prediction strengths emerging across the network. Neuropixels recordings will enable decoding with millisecond precision, such that the first occurrences of mismatch encoding across circuit components (brain regions, cortical layers, neuronal subtypes, and neuronal compartments) can be identified, while imaging experiments will provide denser recordings to measure the broader impact of these predictions on the overall network.

Modeling these responses will be a key integrative effort, facilitating the unification of multi-modal and multi-species datasets. First, analytical metrics derived from real physiological data can be designed and iteratively refined using simulated neuronal activity from cortical models, where the ground truth is known. Second, modeling will enable the multi-modal integration of these datasets by leveraging the relative strengths of various techniques to constrain model parameters. Simulated models will vary in complexity to evaluate our ability to disentangle mechanisms such as adaptation, E/I balance, and other underlying processes.


The analysis can be organized to address three main scientific hypotheses: I) whether mismatch responses are “additive”, “subtractive”, or “multiplicative” in nature; II) whether mismatch responses contain detailed, temporally specific predictions or expectations about the stimulus ensemble; III) whether there exists a common neural mechanism underlying different kinds of mismatch responses. Here, we provide further details about the data analysis and hypothesis testing that this experiment makes possible.

Throughout all hypotheses, we will leverage a shared set of metrics computed on all datasets. **Encoding metrics** should include measures used to evaluate deterministic models, like linear and logistic regressions, such as accuracy, mean square error, and the coefficient of determination R2, or for probabilistic models such as generalized linear models (GLMs). **Decoding metrics** should include measures from pattern clustering and/or classification, for e.g., Mahalanobis distance, confusion matrix (categorical variables) or F1 score, mutual information, or bit rate/latency (for BCIs). In addition, analysis of response distribution across anatomical location and cell types will be used to test all hypotheses.

### I. What kind of information is encoded by mismatch responses?

A. *<u>Multiplicative novelty:</u>* Stimulus-specific enhancement for novel / unpredicted stimuli

B. *<u>Additive novelty:</u>* A generalized “alert” signal that encodes novelty per se

C. *<u>Subtractive novelty:</u>* The difference between the expected vs. actual stimulus

D. *<u>No effect:</u>* In particular, this empirical outcome could constitute a form of rejection of the hypothesis that predictive computation was involved in the experimental conditions tested

#### ***Analysis \#1:*** For each neuron and each mismatch stimulus, construct either the event-triggered average (ETA; for Ca<sup>++</sup> imaging data) or peri-stimulus time histogram (PSTH; for Neuropixel data):

- Significant mismatch responses will be determined in each neuron by comparing activity evoked by a given mismatch stimulus to that same stimulus when it appears during the appropriate control setting. For session 1, this will be a comparison to the spaced randomized control. For session 2, this will be a comparison to the open loop pre-recorded sequence. For session 3, this will be a comparison to the contiguous randomized sequence control. For session 4, this will be the response to a time interval presented as an oddball to the same time interval in random order.

- The significance of mismatch responses will be rigorously tested using bootstrap resampling, to avoid making the assumption of normal statistics for each neuron (which is often a poor assumption). Neurons with p \< 0.01 will be considered “mismatch” neurons.

- Assuming that mismatches occur at random times on an interval \[ITI<sub>min</sub>, ITI<sub>max</sub>\], then the ETA from t = –ITI<sub>min</sub> to t = 0 serves as a baseline response.

- *Absolute response measure*: integrated neural activity over a time window shifted by a standard latency (~50-100 ms).

- *Relative response measure:* integrated neural activity minus baseline activity (use a longer time window for baseline for better SNR, but then scale the integral to compare to the activity at t \> 0).

#### ***Analysis \#2:*** Compare the mismatch response in the novel vs. control conditions:

A. Make a scatter plot of responses in the two conditions and carry out a linear fit. Here are possible interpretations of this analysis, keeping in mind that the data may exhibit combinations of these outcomes:

- multiplicative novelty coding = slope of linear fit \> 1

- additive novelty coding = offset of linear fit \> 0

- subtractive novelty coding = slope of linear fit is not statistically different from zero (or extensive deviation for a subset of neurons)

- no effect = neurons on the identity line

#### ***Analysis \#3:*** Compare responses to different mismatch stimuli in the novel condition (for Sessions 1 and 2):

- Calculate the relative response to the four different mismatch stimuli

- If neurons encode subtractive novelty, then the following will be true:

  1. R(downward, 90° shift) > R(45° shift), because this is a bigger change in orientation

  2. R(halt) < R(90°) and R(45°), because the halt involves a smaller change in velocity

- Other possibilities: i) make some index that captures this relationship for individual neurons, ii) calculate the fraction of neurons fulfilling these conditions and compare them to a shuffle test, iii) assess the effects of depth and subregion on fraction of neurons showing mismatch responses, and compare between types (different sessions).

#### ***Analysis \#4:*** Calculate decoding performance / information encoded for mismatch stimuli and novelty *per se*:

- What fraction of neurons encode significant info about novelty per se?

  - a large fraction indicates a major, distributed encoding of novelty per se

- What fraction of neurons encode significant info about individual mismatch stimuli?

  - a large fraction indicates a major, distributed encoding of the identity of novel stimuli

- Calculate decoding performance vs. N neurons, extrapolate to large N:

  - extrapolation → ~1 indicates strong encoding (expected for individual stimuli, but unclear for novelty *per se*)

- Compare decoding performance of novelty *per se* vs. performance for individual stimuli:

  - similar performance indicates a strong encoding of novelty *per se*

  - lower performance for novelty indicates a weak or secondary encoding of novelty

- Scatter plot of info encoded for novelty vs. individual stimuli:

  - high correlation indicates a joint encoding of novelty and stimulus identity

  - low correlation indicates a separate encoding of novelty and stimulus identity.

### II. Distinguish between two categories of prediction made by neurons:

A. *<u>Detailed predictions</u>* about the identity of the upcoming stimulus

B. Deviation of stimulus probability from the expected *<u>stimulus ensemble</u>*, often described in the literature as “adaptation”. This empirical outcome could be interpreted as a form of refutation of the hypothesis that predictive computation was involved in the experimental conditions tested.

#### ***Analysis \#1:*** Compare the response to the same mismatch stimulus in all three conditions for the sensorimotor mismatch (session 2):

- Is the mismatch response \> for closed loop vs. open loop

  - YES indicates that the neuron encodes a detailed prediction (as only the closed loop condition allows a detailed prediction)

- Is the mismatch response \> control vs. open loop

  - YES indicates that the neuron encodes deviation from the expected ensemble (as a blank is differs more from the mismatch grating than the vertically oriented grating present in the closed loop condition)

#### ***Analysis \#2:*** Calculate decoding performance / info encoded for individual mismatch stimuli vs. for novelty *per se*.

- Use population decoder to identify the occurrence of an individual mismatch stimulus (target) versus all the other neural activity; start with a linear decoder (support vector machine):

  - this quantifies the fidelity for encoding the identity of each of 4 mismatch stimuli

- In a complementary fashion, calculate the mutual information each neuron represents about an individual mismatch stimulus versus all other neural activity

- Similarly, calculate decoding performance and information for a comparison of neural activity during any mismatch stimulus vs all other neural activity;

  - this quantifies the fidelity for encoding stimulus novelty *per se*

- If significantly more information is encoded in the closed loop condition vs. open loop

  - YES indicates encodes of a detailed prediction

- If significantly more information is encoded in the control condition vs. open loop

  - YES indicates encoding of a deviation from the expected ensemble

#### ***Analysis \#3:*** Emergence of Prediction Signals in Single Neurons and Neural Populations

When new, arbitrary correlations are created by the experimenter, the brain must, in principle, learn these new correlations. This can be demonstrated by showing several kinds of changes in neural responses to the same stimuli over time. These changes may occur within a single recording session, which is often interpreted as a form of adaptation, or across recording sessions, which is typically interpreted as learning.

*Key Hypothesis Tests:*

- <u>Predictive coding vs. static tuning:</u> Do individual neurons or neural populations show changes in their response to the same oddball stimuli?

  - YES indicates evidence of predictive computation

  - NO indicates evidence of static or previously learned tuning to stimuli

- <u>“Predictive” Activity:</u> Do neurons or populations of neurons exhibit activity that systematically depends on what the upcoming stimulus is (as can be demonstrated by changing stimulus contingencies)?

  - YES suggests that the neural activity was in part encoding the identity of the upcoming stimulus

  - NO indicates that the neural activity encodes the identity of the current stimulus

- <u>“Pattern completion” activity:</u> Do neurons or populations of neurons exhibit activity during stimulus omission that depends systematically on the preceding stimulus?

  - YES indicates a form of predictive computation, in which predictions are embodied, in part, by specific neural activity driven by events that predict an upcoming stimulus (rather than by the stimulus itself)

  - NO indicates that a response to the omission itself

- <u>Latent component dynamics:</u> Do identified latent variables exhibit systematic changes over trials?

  - YES indicates evidence of predictive computation revealed only at the population level

- <u>Neural dimensionality reduction:</u> Does the manifold structure of mismatch responses shift toward a more compact, lower-dimensional space with repeated exposure?

  - YES indicates a structure of predictive computation that is consistent with theories about efficient coding and/or maximization of coding capacity

- <u>Conjunctive vs. disentangled representation:</u> Does the visualized geometric structure of population activity embedded in a 3D space; e.g., using unsupervised UMAP (Uniform Manifold Approximation and Projection), show distinct, possibly orthogonal, trajectories that could reveal disentangled coding schemes for different signals (e.g., for stimulus evoked responses vs. prediction errors)?

  - YES indicates that the population neural code can simultaneously represent information about the stimulus as well as its predictive context

*Single Neuron Analysis:* Determine whether individual neurons exhibit changes in their responses with repeated oddball presentations, indicative of learning.

- <u>Trial-by-Trial Response Analysis:</u> Measure the amplitude and timing of neuronal responses to each oddball stimulus across trials.

- <u>Model Fitting:</u> Apply exponential or linear decay models to these responses to measure trends over time.

- <u>Statistical Validation:</u> Use bootstrap resampling to evaluate the significance of observed changes.

- <u>Time Points for Analysis:</u> Pre-Oddball Baseline Period: A period before the oddball onset (e.g., -200 ms to stimulus onset at 0 ms) to establish baseline activity levels. Oddball Response Window: A post stimulus onset interval (e.g., 0 to 300 ms) capturing the immediate neuronal response to the oddball stimulus.

*Population Latent Analysis:* Identify latent patterns within neural populations that correspond to predictions and prediction error signals.

- <u>Tensor Component Analysis (TCA):</u> Decompose multi-dimensional neural data to uncover components with trial-dependent dynamics.

- <u>Time Points for Analysis:</u> Pre-Oddball Baseline: A period before oddball onset (e.g., -200 ms to stimulus onset at 0 ms) to establish baseline population activity levels. Oddball Response Window: The duration of the oddball stimulus presentation (e.g., 0 to 300 ms) capturing immediate population responses to the oddball stimulus. Post-Oddball Period: A post stimulus offset interval (e.g., 300 ms to 600 ms) to monitor any sustained or delayed responses. Inter-Trial Intervals: Periods between oddball trials to evaluate baseline stability and potential anticipatory activity.

*Cross-Day Analysis:* Monitor the activity of individual neurons or neural populations over time to identify changes in prediction error signaling and learning processes.

### III. Mismatch responses across different types of predictions

These experiments test mismatch responses resulting from different kinds of predictions: i) repetition vs. oddball (session 1), sensorimotor mismatch (session 2), and temporal sequence prediction (session 3 and 4). Are there different circuit mechanisms for these four kinds of prediction?

In particular, sensorimotor prediction requires a corollary discharge of the motor command, so it requires feedback from outside V1. While there is evidence for feedback from higher-level cortex for oddball responses, reduced oddball responses seem to remain after blocking this feedback. Temporal sequence prediction could, in principle, be carried out by recurrent neural circuits within V1, but it is likely that feedback from higher cortex could enhance or extend these predictions.

Importantly, if the outlined paradigms show the same essential distribution of feature-based mismatch responses across areas and layers, then this would argue against the hypothesis for distinct mechanisms.

#### ***Analysis \#1:*** Map the locations of neurons showing significant mismatch responses using two-photon imaging and neuropixels recordings.

- For spatial analyses, we will focus on the firing rate (using a deconvolution approach for Ca<sup>++</sup> imaging) averaged over all timepoints (e.g., 0 to 275 ms) for each trial. For each cohort, we will map the density of mismatch neurons as a function of region, layer, and cell-type. We will compare the percentage of mismatch responses (over all responsive neurons; each mouse as one observation) using a mixed ANOVA with paradigm (paradigm 1, 2, or 3) as a between subjects variable and region and layer as within subjects variables. Sex and mouse age will be covariates. We will carry out a separate analysis for each method (two-photon vs neuropixel) and cell-type (two-photon imaging of PYRs and interneurons subtypes).

- Using PSTHs, compute the variability (standard deviation) of spike times relative to stimulus onset, as well as peak latency; compare to different models and across experimental conditions.

- Use dimensionality reduction techniques (principal components analysis (PCA), t-distributed stochastic neighbor embedding (t-SNE), UMAP, *etc*.) to visualize population activity across units and identify functional clusters.

- Characterize how different coding subspaces are oriented relative to each other in neural state space by computing the joint angles [@rule2020stable].

- Another approach would be to examine how much the coding direction of one variable aligns with the direction of another variable.

#### ***Analysis \#2:*** Compare responses for the \*same\* neurons between sensorimotor (session 2) and temporal sequence (session 3) mismatches.

- Is the mismatch response stronger for sensorimotor than temporal sequence prediction?

  - YES suggests different neural circuits for these two kinds of prediction

  - NO suggests common circuitry may explain data

- Make a scatter plot of mismatch response in sensorimotor vs. temporal sequence prediction

  - data scattering all over the plane suggests different neural circuits for these two kinds of prediction

  - data falling near a line suggests that additional circuitry for sensorimotor prediction “feeds into” common circuits

- Are there more examples of ‘pure mismatch responses’ (i.e. no baseline activity) in sensorimotor prediction vs. others

  - YES suggests different neural circuits for these different kinds of prediction

#### **Analysis \#3:** Compare responses for the \*same\* neurons between the oddball (session 1) and sequence (session 3) mismatches.

- For comparing magnitudes of mismatch responses, the average firing rate for each neuron showing a significant mismatch response will be averaged over trials, and then layers and regions. We will compare these values using a mixed ANOVA with paradigm (session 1, 2, 3 or 4) as a between-subjects variable and region and layer as within-subjects variables.

- Is the mismatch response stronger for repetition than temporal sequence prediction?

  - YES suggests different neural circuits for these two kinds of prediction

  - NO suggests common circuitry may explain data

- Make a scatter plot of mismatch response in oddball vs. temporal sequence prediction

- data scattering all over the plane suggests different neural circuits for these two kinds of prediction

- data falling near a line suggests that additional circuitry for oddball prediction “feeds into” common circuits

#### ***Analysis \#4:*** Analysis of recording from inhibitory interneurons.

- Are inhibitory neurons more strongly activated in session 2?

  - YES suggests that there is feedback from higher cortical areas

- Is inhibitory activity stronger in closed loop vs. open loop (session 2)?

  - YES inhibitory activity may reflect a sensory prediction

- Similar analyses for sessions 1 and 3

#### ***Analysis \#5:*** Temporal Mismatch Analysis (session 4).

- Test whether baseline activity and/or visual evoked responses under control conditions are different than for temporally deviant visual stimuli

  - YES indicates neurons encode specific temporal predictions about the time of occurrence of stimuli

- Assess how distinct classes of interneurons contribute to predictive timing by examining their responses to temporally based mismatches when the stimulus duration deviates from the control condition

#### **Analysis \#6:** Test various prediction models across session types.

- Quantify learning effects as a function of region and layer. Measure the response amplitude before and after repeated presentations of the same stimulus within a recording session.

- Analyze changes in neural responses within a recording session (e.g., occurring over periods of seconds to minutes) to detect patterns likely to reflect short-term memory processes. Compute autocorrelations and cross-correlations across spike trains.

- Train deep learning models using self-supervised learning (e.g., to predict future activity from past activity) to extract latent feature representations of the neural data. Analyze the accuracy of stimulus decoders trained on the representations extracted from different areas and using different temporal windows.

- Analyze changes in neural activity patterns across learning days to detect patterns likely to reflect longer-term experience-dependent plasticity processes.

- Use information theory criteria and cross-validation techniques to compare the goodness-of-fit of different models. Validate models using separate test datasets, including ones obtained from different laboratories.

# Conclusion

:::{warning} Work in progress
:class: manuscript-wip
The conclusion has not yet been drafted.
:::

## Supplementary figures

:::{figure} ./images/figures/imported/supplementary-neuropixels-implant-trajectories.png
:label: fig-supp-neuropixels-implant-trajectories
:alt: Four-panel Neuropixels implant figure showing six planned probe trajectories, atlas structures along each trajectory, stereotaxic coordinates, and implant-hole geometry.
:enumerated: false
:width: 100%

**Supplementary Figure 1.** Neuropixels implant geometry and planned probe trajectories. **A,** Six trajectories (A-F) through the Allen Mouse Brain Common Coordinate Framework. **B,** Atlas structures intersected by each trajectory. **C,** Anteroposterior and mediolateral coordinates relative to bregma with implant-hole diameters D1 and D2. **D,** Top view of the implant with labeled probe-access holes.
:::

:::{iframe} ./interactive/unit-yield.html
:label: fig-supp-neuropixels-unit-yield
:enumerated: false
:width: 100%
:title: Supplementary Figure 2. Neuropixels unit yield across recording days.

**Supplementary Figure 2.** Neuropixels unit yield across recording days. Individual lines show 60 sessions from 16 mice; the bold line shows the daily mean, and *n* is the number of sessions represented on each day. Units passed all three quality-control thresholds (ISI-violations ratio < 0.5, presence ratio > 0.8, and amplitude cutoff < 0.1). QC-passing units were divided by the number of recorded probes and normalized to each mouse's day-1 value. Mean yield declined from 100% on day 1 to 80.9% on day 4. Values were derived from the public draft of Dandiset 001637 retrieved July 30, 2026.
:::

:::{iframe} ./interactive/neuropixels-trajectories.html
:label: fig-supp-neuropixels-recorded-trajectories
:enumerated: false
:width: 100%
:title: Supplementary Figure 3. Recorded Neuropixels trajectories in the Allen CCF.
:placeholder: ./images/figures/generated/supplementary-neuropixels-trajectories.svg

**Supplementary Figure 3.** Recorded Neuropixels trajectories in the Allen Mouse Brain Common Coordinate Framework (CCF) 2017. The **Interactive** view renders all CCF-localized insertions within a semi-transparent whole-brain surface and supports mouse, probe-port, camera-orientation, and brain-opacity controls. Selecting a trajectory shows its session, localized shank length, source NWB, and contiguous CCF area profile from the dorsal shank end to the tip. Line color denotes the nominal probe port (A-F). In the **Static** view, **A,** an oblique projection shows the trajectories across the depth-shaded Allen CCF whole-brain surface; **B,** a dorsal projection shows their anteroposterior and mediolateral distribution. Both panels use a semi-transparent brain surface, anatomical direction markers, and calibrated 2 mm scale bars; the trajectories extend laterally toward the L direction marker, matching the stereotaxic mediolateral convention. Electrode coordinates and area annotations come from the public draft of Dandiset 001637; the brain surface is a 100-micrometer mesh derived from the Allen CCF 2017 25-micrometer annotation volume. In total, 332 probe trajectories from 57 sessions and 16 mice had finite CCF coordinates. Three of the 60 source sessions are excluded because their NWB electrode tables lack `x`, `y`, and `z` coordinates.
:::

:::{iframe} ./interactive/eye-tracking-viewer.html
:label: fig-supp-eye-tracking
:enumerated: false
:width: 100%
:title: Supplementary Figure 4. Synchronized eye tracking across recording modalities.

**Supplementary Figure 4.** Synchronized eye tracking in representative standard-oddball Neuropixels, mesoscope, and SLAP2 sessions. The **Interactive** view shows the public eye-camera video, reconstructed visual stimulus, and processed eye fits on a common 16-second clock. Fit-source tabs switch the center field, geometric values, and area trace among the pupil, corneal reflection, and eye ellipse. Marker position gives the selected fit center within the complete camera frame; the dashed crosshair marks its median center across valid nonblink fits from that source session. Marker size and color vary with selected-fit area after scaling to that fit's session-wide 5th–95th percentile nonblink range. The tracking field turns black during likely-blink samples, which are also shown as shaded intervals in the area trace. The **Static** view vertically stacks the raw pupil x position, y position, and area for each modality on the same 0–16-second axis. Teal bands mark the complete 90-degree orientation-deviant presentation and gray bands mark likely-blink intervals; traces break at invalid fits rather than interpolating through them. Neuropixels and mesoscope eye-camera frames are aligned through 100-kHz exposure edges in the session sync file, with reported dropped frames removed before mapping to MP4 time. SLAP2 uses aligned Harp timestamps and packaged pupil-frame indices to map the processed fits to its 30 Hz EyeCamera MP4. Eye fits, blink flags, and stimulus rows come from each public NWB time base. Modality tabs switch among all three source-backed examples, and source links expose the corresponding DANDI and raw S3 records.
:::

:::{iframe} ./interactive/optotagging-heatmaps.html
:label: fig-supp-optotagging-heatmaps
:enumerated: false
:width: 100%
:title: Supplementary Figure 5. Optotagging responses and putative optotagged-cell yield.
:placeholder: ./images/figures/generated/optotagging-heatmaps.svg

**Supplementary Figure 5.** Optotagging responses and putative optotagged-cell yield across Neuropixels sessions. The **Interactive** view displays laser-aligned, baseline-z-scored 1-ms peri-stimulus time histograms for three representative public sessions selected near the 50th, 80th, and 95th percentiles of optotagged-cell yield. Session and Allen major-parent selectors constrain the view to available values, and an adjustable symmetric z-score scale supports comparison of raised-cosine, 5 Hz, and 40 Hz stimulation. Within each condition, units are ordered from strongest to weakest by firing rate measured only during the exact laser-on windows. In the **Static** view, **A,** the 5 Hz response from `ecephys_830851_2026-03-19_10-49-11`; five teal marks denote the exact 10 ms laser pulses, rows are ordered from strongest to weakest pulse-window firing rate, and blue-to-red color denotes negative-to-positive baseline z score. **B,** Overall optotagged-cell yield across all 60 source sessions. **C,** Yield by Allen major parent area. **D,** The 18 structures with the highest mean yield; all 48 structure distributions remain in the supplied source snapshot. In B-D, gray dots denote individual sessions and teal bars or lines denote means. Area-level means include only sessions sampling that area, with the contributing session count shown as *n*. Data come from the public draft of [Dandiset 001637](https://dandiarchive.org/dandiset/001637/draft/files).
:::


# Supplementary Text 1: Published oddball paradigms and sampling ranges

[Supplementary Table 1](#table-supplementary-oddball-studies) compares five published visual oddball paradigms with respect to stimulus design, timing, sample size, recording method, statistical test, habituation, and sampling.

:::{iframe} ./interactive/literature-comparison.html
:label: table-supplementary-oddball-studies
:enumerated: false
:width: 100%
:title: Supplementary Table 1. Published oddball paradigms and sampling parameters.

**Supplementary Table 1.** Compare one paradigm parameter across all studies or inspect the complete
profile of one study. Search filters the visible records in either view, and
CSV export contains exactly the displayed subset.
:::

The paradigms span visuomotor decoupling and local or global deviations in visual sequences. Three studies used two-photon calcium imaging, one used local field potentials, and one used Neuropixels recordings.

Reported oddball probabilities ranged from 0.07 to 0.20, the reported number of oddball repeats required ranged from 10 to 144, and session durations ranged from 6 minutes to 2 hours. This comparison informed the mismatch repeat count and session duration used in the present dataset; differences in stimuli, response definitions, and significance tests should be considered when comparing responsive-neuron fractions across studies.

# Glossary

:::{dropdown} Terms and abbreviations

Abbreviations indicate the relevant modality:

*meso* = mesoscopic 2-photon Ca2+-imaging

*ephys* = electro-physiology (neurophysiology) using Neuropixels probes

ophys = optical-physiology using any *in vivo* fluorescence imaging technique

*slap2 =* SLAP2 glutamate vesicle imaging

**ROI** (*slap2*): Region of interest: a localized candidate location of a synaptic spine.

**(Single) Unit** (*ephys*)**:** A candidate for an isolated single neuron.

**Receptive Field** (*meso*/*ephys*/*slap2*): A region of sensory (here: visual) space where an isolated stimulus evokes a neuronal response (either increases or decreases neuronal activity).

**Orientation Tuning** (*meso*/*ephys*/*slap2*): The selective response of visual neurons to edges or bars at particular angles.

**NWB:** Neurodata Without Borders. Standardized file format specification that stores neuronal physiology data. Used to store data for all modalities in this work.

**DANDI**: The DANDI Archive (Distributed Archives for Neurophysiology Data Integration) is a public repository supported by the US BRAIN Initiative. It allows scientists to store, publish, and access cellular neurophysiology data, such as electrophysiology, optical physiology, and behavioral time-series.
:::
