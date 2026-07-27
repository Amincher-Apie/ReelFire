import assert from "node:assert/strict";
import test from "node:test";

import {
  pageForIndex,
  paginate,
} from "../static/js/utils/pagination.js";

test("paginate defaults to five items and clamps page boundaries", () => {
  const items = Array.from({ length: 12 }, (_, index) => index + 1);

  const first = paginate(items);
  assert.deepEqual(first.items, [1, 2, 3, 4, 5]);
  assert.equal(first.page, 1);
  assert.equal(first.pageCount, 3);

  const last = paginate(items, 99, 5);
  assert.deepEqual(last.items, [11, 12]);
  assert.equal(last.page, 3);
  assert.equal(last.startIndex, 10);
  assert.equal(last.endIndex, 12);
});

test("page size has no artificial upper limit", () => {
  const items = Array.from({ length: 1500 }, (_, index) => index);
  const page = paginate(items, 1, 1500);

  assert.equal(page.items.length, 1500);
  assert.equal(page.pageCount, 1);
  assert.equal(page.pageSize, 1500);
});

test("pageForIndex locates selected items in a bounded list", () => {
  assert.equal(pageForIndex(0, 5), 1);
  assert.equal(pageForIndex(4, 5), 1);
  assert.equal(pageForIndex(5, 5), 2);
  assert.equal(pageForIndex(24, 10), 3);
});
