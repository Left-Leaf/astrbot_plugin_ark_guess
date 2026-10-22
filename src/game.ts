export interface Operator {
  id: string;
  name: string;
  rarity: number;
  profession: string;
  subclass: string;
  faction: string;
  faction_hidden: string[];
  race: string;
  release_year: number;
}

export type FieldState = "correct" | "close" | "wrong" | "higher" | "lower";
export type GameStatus = "playing" | "won" | "lost";

export interface GuessResult {
  rarity: FieldState;
  subclass: FieldState;
  faction: FieldState;
  race: FieldState;
  release_year: FieldState;
}

export interface GuessRecord {
  operatorId: string;
  result: GuessResult;
}

export interface GameSession {
  answerId: string;
  guesses: GuessRecord[];
  maxAttempts: number;
  status: GameStatus;
  startedAt: number;
  finishedAt?: number;
}

export interface LocalStats {
  gamesPlayed: number;
  gamesWon: number;
  currentStreak: number;
  bestStreak: number;
}

export interface SavedGameData {
  version: 1;
  session: GameSession | null;
  stats: LocalStats;
}

export const MAX_ATTEMPTS = 8;
export const STORAGE_KEY = "ark-operator-guess:v1";

export function splitFactions(value: string): Set<string> {
  return new Set(
    value
      .split(/[,，;；、]/)
      .map((part) => part.trim())
      .filter(Boolean),
  );
}

function factionOverlap(left: Set<string>, right: Set<string>): boolean {
  return [...left].some((faction) => right.has(faction));
}

function compareNumber(guess: number, answer: number): FieldState {
  if (guess === answer) return "correct";
  return guess < answer ? "higher" : "lower";
}

export function compareOperators(guess: Operator, answer: Operator): GuessResult {
  const subclass: FieldState =
    guess.profession.trim() !== answer.profession.trim()
      ? "wrong"
      : guess.subclass.trim() === answer.subclass.trim()
        ? "correct"
        : "close";

  const guessMain = splitFactions(guess.faction);
  const answerMain = splitFactions(answer.faction);
  const guessAll = new Set([...guessMain, ...guess.faction_hidden.map((item) => item.trim()).filter(Boolean)]);
  const answerAll = new Set([...answerMain, ...answer.faction_hidden.map((item) => item.trim()).filter(Boolean)]);
  const faction: FieldState = factionOverlap(guessMain, answerMain)
    ? "correct"
    : factionOverlap(guessAll, answerAll)
      ? "close"
      : "wrong";

  return {
    rarity: compareNumber(guess.rarity, answer.rarity),
    subclass,
    faction,
    race: guess.race.trim() === answer.race.trim() ? "correct" : "wrong",
    release_year: compareNumber(guess.release_year, answer.release_year),
  };
}

export function createGame(
  operators: Operator[],
  random: () => number = Math.random,
  now = Date.now(),
): GameSession {
  if (operators.length === 0) throw new Error("题库为空，无法开始游戏。");
  const answer = operators[Math.floor(random() * operators.length)];
  return {
    answerId: answer.id,
    guesses: [],
    maxAttempts: MAX_ATTEMPTS,
    status: "playing",
    startedAt: now,
  };
}

export function submitGuess(
  session: GameSession,
  guess: Operator,
  operatorsById: Map<string, Operator>,
  now = Date.now(),
): GameSession {
  if (session.status !== "playing") throw new Error("本局已经结束，请开始新一局。");
  if (session.guesses.some((record) => record.operatorId === guess.id)) {
    throw new Error(`「${guess.name}」已经猜过了。`);
  }
  const answer = operatorsById.get(session.answerId);
  if (!answer) throw new Error("本局答案无效，请刷新页面重新开始。");

  const guesses = [...session.guesses, { operatorId: guess.id, result: compareOperators(guess, answer) }];
  const status: GameStatus =
    guess.id === answer.id ? "won" : guesses.length >= session.maxAttempts ? "lost" : "playing";
  return {
    ...session,
    guesses,
    status,
    ...(status === "playing" ? {} : { finishedAt: now }),
  };
}

export function defaultStats(): LocalStats {
  return { gamesPlayed: 0, gamesWon: 0, currentStreak: 0, bestStreak: 0 };
}

export function searchOperators(operators: Operator[], query: string, limit = 8): Operator[] {
  const term = query.trim().toLocaleLowerCase();
  if (!term) return [];
  return operators
    .map((operator) => {
      const name = operator.name.toLocaleLowerCase();
      const id = operator.id.toLocaleLowerCase();
      const rank = name === term || id === term ? 0 : name.startsWith(term) ? 1 : name.includes(term) || id.includes(term) ? 2 : 3;
      return { operator, rank, matches: rank < 3 };
    })
    .filter((entry) => entry.matches)
    .sort((left, right) => left.rank - right.rank || left.operator.name.localeCompare(right.operator.name, "zh-CN"))
    .slice(0, limit)
    .map((entry) => entry.operator);
}
