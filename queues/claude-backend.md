# Queue — Claude backend seat
1. [ ] GRAPH-FIRST: pull graph library slices for graph-db/backend prior art
   (TOPICS.md → slices) before designing.
2. [ ] Design + build world/backend/: bridge from graphify index.db (9.2M
   nodes; FTS) + FalkorDB (port 16379) into evo shared state/scratchpad, so
   subagents can pull prior-art slices mid-experiment.
3. [ ] Wire as an evo skill or hook so it rides the normal plugin surface.
