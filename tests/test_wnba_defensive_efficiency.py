from utils.wnba_defensive_efficiency import possessions


def test_possessions_dean_oliver():
    # 80 FGA, 20 FTA, 10 OREB, 12 TOV → 80 + 8.8 - 10 + 12 = 90.8
    assert possessions(80, 20, 10, 12) == 90.8
