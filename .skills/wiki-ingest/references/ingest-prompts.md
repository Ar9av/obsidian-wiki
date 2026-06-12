# Ingest Prompt Templates

These are the mental frameworks to use when distilling a source into wiki pages.

## Knowledge Extraction Frame

When reading a source document, ask yourself:

1. **What are the 3-5 most important ideas in this document?**
   These become concepts pages or updates to existing concept pages.

2. **Who or what is mentioned that deserves its own page?**
   People, tools, organizations, projects → entity pages.

3. **What does this document teach you how to do?**
   Procedures, workflows, techniques → skills pages.

4. **What claims does this document make?**
   Each claim needs a source attribution. If it contradicts an existing wiki claim, note the contradiction.

5. **How does this connect to what the wiki already knows?**
   This is the most important question. The value of the wiki compounds through connections.

## Paper Extraction Frame

For academic papers (ML/AI/LLM/VLM and similar), the generic frame above misses what makes a paper legible. Add these questions:

1. **What problem does it solve, and what's new?** The one-sentence thesis + the single most important result.
2. **What is the method?** Which figure shows the architecture/pipeline? Sketch it as a Mermaid flowchart — capture the data flow, not just the component names.
3. **What are the core equations?** The 1–3 that define the mechanism — keep them as math (`$$…$$`), not prose.
4. **What's the experimental setup and the headline numbers?** Datasets, baselines, and the metric table the paper is judged on.
5. **What are the ablations and limitations?** What did they vary, and what does the method *not* do?

These map onto the Paper Deep-Dive Template in `llm-wiki/SKILL.md`. The goal is a page a reader could study instead of the PDF — figures, equations, and results included.

## Synthesis Frame

When a new source covers ground that existing pages already cover:

- Don't duplicate — synthesize
- If the new source agrees with existing content, strengthen the claims with additional attribution
- If it disagrees, create an "Open Questions" or "Debate" section noting both positions
- If it adds nuance, weave it into the existing narrative

## Cross-Reference Discovery

After extracting knowledge, look for these connection patterns:

- **Is-a**: "Transformers are a type of neural network" → link from transformer page to neural-network page
- **Uses**: "RLHF uses reward models" → link from RLHF to reward-models
- **Contrasts-with**: "CNNs vs. Transformers for vision" → mutual links
- **Part-of**: "Attention is a component of transformers" → link from attention to transformers
- **Created-by**: "Transformers were introduced by Vaswani et al." → link to entity page
- **Applied-in**: "Transformers are used in GPT" → link from transformers to GPT
