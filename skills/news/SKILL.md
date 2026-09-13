---
name: news
description: Display prioritized news headlines by category (crypto, macro, tech, geo)
user-invocable: true
---

# News

Read cached headlines through the installed NewsStore after verifying the
configured core, data root and canonical space. Do not refresh or execute
checkout code during automatic context loading. Refresh only as an explicit
step of the requested news workflow, and surface retrieval/migration failures.

## Instructions

Follow the full workflow in `commands/news.md` in this installed module.

Usage: `/news [category]` where category is: crypto, macro, tech, geo, or all (default)

Parse `$ARGUMENTS` for optional category filter.

Display headlines in three tiers (high/medium/low priority) based on relevance scoring. Include source, category tag, and relevance score for each item.
