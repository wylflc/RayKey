"""Register the second-stage eight neighbors without changing the frozen first-stage engine."""
import engine
from policy import grid


def neighbors():
    return [dict(arm=f'C{cap:03}R{release:02}',kind='hysteresis',cap=cap/100,release=release/1000)
            for cap in (70,90) for release in (30,35,40,45)]


if __name__ == '__main__':
    engine.grid = lambda: grid()+neighbors()
    raise SystemExit(engine.main())
