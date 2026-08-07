# 🌾 Dimitri

Dimitri is an AI agent built for the Kaggriculture Kaggle simulation competition.

The project is designed around a modular decision-making architecture inspired by real-world AI systems.

## Architecture

```
Kaggle Observation
        │
        ▼
     Observer
        │
        ▼
    GameState
        │
        ▼
     Analyst
        │
        ▼
     Planner
        │
        ▼
    Executive
        │
        ▼
     Operator
```

## Engineering Principles

1. Identify the current bottleneck.
2. Compare actions, not objects.
3. Plans are hypotheses.
4. Replan only when evidence suggests a better path.
5. Optimize the system rather than individual actions.
6. Every important decision should be explainable.
7. Prefer the simplest architecture that satisfies today's requirements.

---

Currently under active development.

Current Sprint

Sprint 1

Completed

✅ GameState
✅ Player
✅ Inventory
✅ Market
🚧 Parser