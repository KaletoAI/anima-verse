"""The improvements queue: long-running asset work done in user-idle time.

`base` is the contract every improvement type implements, `registry` the
name→type map the engine looks through, `store` the world.db layer. The
engine that executes the steps lives outside this package — nothing here
knows about the task queue.
"""
