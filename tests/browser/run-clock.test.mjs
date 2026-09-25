import assert from "node:assert/strict";
import test from "node:test";
import {RunClock} from "../../website/run-clock.mjs";

test("clock starts at click, never rewinds on replay, and freezes at completion", () => {
  let now = 0; const clock = new RunClock(() => now); clock.start();
  now = 2000; assert.equal(clock.sample().total, 2);
  clock.observe({elapsed: 1, timings_seconds: {laya: 0.5}, timing_phase: "laya"});
  now = 3000; assert.equal(clock.sample().total, 3);
  clock.observe({elapsed: 2});
  now = 4000; assert.equal(clock.sample().phases.laya, 2.5);
  clock.observe({elapsed: 3.5, timings_seconds: {laya: 1, search: 2}, timing_phase: "search"});
  now = 5000; assert.deepEqual(clock.sample().phases, {laya: 1, search: 3});
  clock.stop(); now = 99000; assert.equal(clock.sample().total, 5);
});

test("a late join gets server elapsed and independently measured phases", () => {
  let now = 0; const clock = new RunClock(() => now); clock.start();
  clock.observe({elapsed: 50, timings_seconds: {laya: 3, search: 46}, timing_phase: "search"});
  now = 1000; assert.equal(clock.sample().total, 51);
  clock.stop(); now = 10000; clock.resume(); now = 11000;
  clock.observe({elapsed: 60, timings_seconds: {laya: 3, search: 56}, timing_phase: "search"});
  assert.equal(clock.sample().total, 60);
  clock.reset(); assert.equal(clock.sample().total, 0);
});
