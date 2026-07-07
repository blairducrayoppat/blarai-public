Thanks for looking into this, @YuChern-Intel.

For this issue (#34450), would it make sense for the `as_convolution` pass to return a catchable error rather than triggering a SIGABRT? Currently, when per-group INT4 FC layers produce the degenerate `tensor<1x0x1x1xf16>` shape, the process terminates at the C level — there's no way for the calling application to catch or recover from it. A clean error would let users (and frameworks like GenAI) handle the unsupported case gracefully, even if the underlying limitation remains.

That's essentially what npu_compiler PRs [openvinotoolkit/npu_compiler#265](https://github.com/openvinotoolkit/npu_compiler/pull/265) and [openvinotoolkit/npu_compiler#266](https://github.com/openvinotoolkit/npu_compiler/pull/266) propose — guarding against the degenerate shape before it reaches MLIR type inference. Happy to adjust the approach if the team has a preferred pattern for this.
