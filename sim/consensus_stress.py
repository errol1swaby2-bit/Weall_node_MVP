"""
High-level stochastic stress test for finality.

Includes:
- Nakamoto longest-chain baseline (from Bitcoin whitepaper math)
- VRF epoch placeholder (toy model) for PoH-style slot lotteries

This is for exploration and sanity-checking only.
"""
import math, random

random.seed(0)

def reorg_probability(k: int, adversary: float) -> float:
    """
    Approximate probability that an adversary with share 'adversary'
    can catch up k confirmations behind the honest chain.
    (Classic Satoshi Poisson approximation)
    """
    q = adversary
    p = 1 - q
    lam = k * (q/p)
    s = 0.0
    for r in range(0, k+1):
        # Poisson(lam, r) * (q/p)^(k-r)
        s += math.exp(-lam) * lam**r / math.factorial(r) * (q/p)**(k - r)
    return max(0.0, min(1.0, 1 - s))

def vrf_epoch_reorg_prob(k: int, adversary: float, slots_per_epoch: int = 64):
    """
    Very rough placeholder: assume per-slot leader election with probability ~ stake share.
    Adversary must win enough consecutive slots to rewrite k confirmations.
    Upper bound geometric tail model.
    """
    q = adversary
    return min(1.0, (q / (1-q))**k)

if __name__ == "__main__":
    for a in (0.1, 0.2, 0.3, 0.4):
        print(f"Adversary share a={a:.1f}")
        for k in (1, 2, 3, 6, 12):
            print(f"  k={k:2d}  Nakamoto≈{reorg_probability(k,a):.6f}  VRF≈{vrf_epoch_reorg_prob(k,a):.6f}")
