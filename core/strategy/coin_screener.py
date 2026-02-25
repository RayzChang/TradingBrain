"""
幣種篩選器 (Coin Screener)

從 watchlist 中依 MTF 一致性、趨勢強度、絞肉機迴避等條件，
選出當前最適合交易的一組標的（供策略與風控優先處理）。
"""

from core.analysis.engine import FullAnalysis
from loguru import logger


class CoinScreener:
    """
    對單一幣對的完整分析結果打分，供排序篩選。

    分數越高越適合作為當前交易標的。
    不直接依賴 K 線快取，由呼叫方傳入 FullAnalysis。
    """

    def score(self, full: FullAnalysis) -> float:
        """
        計算單一幣對的「可交易性」分數。

        考量:
        - MTF 趨勢一致且信心高 → 加分
        - HTF RSI 已確認 → 加分
        - 絞肉機行情 → 大幅扣分
        - ADX 有趨勢強度 → 加分

        Returns:
            0.0 ~ 1.0，越高越適合交易
        """
        score_val = 0.0
        primary = full.single_tf_results.get(full.primary_tf)
        if not primary:
            return 0.0

        # MTF 一致且方向明確
        if full.mtf:
            if full.mtf.recommended_direction and full.mtf.confidence > 0:
                score_val += 0.4 * full.mtf.confidence
            if full.htf_rsi_confirmed:
                score_val += 0.2

        # 趨勢強度 (ADX)
        adx = primary.indicators.get("adx")
        if adx is not None:
            try:
                adx_f = float(adx)
                if adx_f >= 25:
                    score_val += min(0.2, (adx_f - 25) / 75)
            except (TypeError, ValueError):
                pass

        # 絞肉機扣分
        if primary.chop and primary.chop.is_chop:
            score_val -= 0.3 + primary.chop.score * 0.3
            score_val = max(0.0, score_val)

        return min(max(score_val, 0.0), 1.0)

    @staticmethod
    def rank(
        symbol_scores: list[tuple[str, float]],
        top_n: int = 5,
        min_score: float = 0.0,
    ) -> list[str]:
        """
        依分數排序，回傳前 top_n 個符號（且不低於 min_score）。

        Args:
            symbol_scores: [(symbol, score), ...]
            top_n: 最多取幾個
            min_score: 低於此分數的符號不列入

        Returns:
            排序後的 symbol 列表
        """
        filtered = [(s, sc) for s, sc in symbol_scores if sc >= min_score]
        filtered.sort(key=lambda x: x[1], reverse=True)
        result = [s for s, _ in filtered[:top_n]]
        if result:
            logger.debug(f"CoinScreener rank: top={result}, scores={[sc for _, sc in filtered[:top_n]]}")
        return result
