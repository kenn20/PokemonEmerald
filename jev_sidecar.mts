/**
 * JSONL bridge for the existing jev-pokemon client.
 *
 * Run this file with tsx from the jev-pokemon checkout. The Python process
 * owns emulator input; this process only receives typed state/options and
 * returns a semantic option ID.
 */

import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const project = process.env.JEV_PROJECT;
if (!project) throw new Error('JEV_PROJECT must point to the jev-pokemon checkout');

const clientPath = pathToFileURL(path.join(project, 'src/jev/client.ts')).href;
const { Jev } = await import(clientPath);
const jev = new Jev({
  mode: 'gateway',
  logFile: process.env.JEV_LOG_FILE ?? 'logs/emerald-jev-calls.jsonl',
});

const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of input) {
  if (!line.trim()) continue;
  try {
    const request = JSON.parse(line);
    const question = request.questions?.decision;
    if (question?.type !== 'choice' || !question.criteria) {
      throw new Error('request must contain a decision choice question');
    }
    const choice = await jev.choose(
      request.purpose ?? 'emerald',
      request.state,
      question.instructions,
      question.criteria,
    );
    process.stdout.write(JSON.stringify({ choice }) + '\n');
  } catch (error) {
    process.stderr.write(`[jev-sidecar] ${String(error)}\n`);
    process.stdout.write(JSON.stringify({ error: String(error) }) + '\n');
  }
}
